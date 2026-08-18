"""Small, standalone Loadout-compatible API for an AMPD Surge deployment.

This is the local calculation surface used by Surge. It deliberately exposes
only calculation and approved reference-data routes; it does not include the
Loadout SaaS login, billing, customer records or admin UI.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("LOADOUT_DATA_DIR", Path(__file__).with_name("data")))
CONFIG_PATH = DATA_DIR / "equipment_config.json"
KNOWLEDGE_PATH = DATA_DIR / "loadout_knowledge.json"
MANUFACTURER_DIR = DATA_DIR / "manufacturers"

app = Flask(__name__)

with CONFIG_PATH.open(encoding="utf-8") as handle:
    _config = json.load(handle)
EQUIPMENT_SPECS = _config.get("equipment_specs", {})
DEMAND_FACTORS = _config.get("demand_factors", {"Tower Crane": 0.28, "Crane": 0.28, "Hoist": 0.80})
UTIL_RATES = _config.get("util_rates", {"Tower Crane": 0.10, "Crane": 0.10, "Hoist": 0.30})

with (DATA_DIR / "generator_rates.json").open(encoding="utf-8") as handle:
    _rate_data = json.load(handle)
GEN_RENTAL_PRICES = {int(k): float(v) for k, v in _rate_data["weekly_hire_rates"].items()}
with (DATA_DIR / "bess_units.json").open(encoding="utf-8") as handle:
    _bess_rows = json.load(handle)
AMPD_UNITS = {
    row["name"]: {
        "continuous_kva": row["continuous_kva"], "peak_kva": row["peak_kva"],
        "continuous_kw": row["output_kw"], "peak_kw": row["peak_kw"],
        "input_kw": row["charge_rate_kw"], "capacity_kwh": row["capacity_kwh"],
    }
    for row in _bess_rows
}
AMPD_RATES = {"Ampd 200": 1200, "Ampd 400": 2000}
RECHARGE_GENS = {
    "Ampd 200": {"charge_kw": 60.0, "standby_kw": 1.5, "fuel_lph_at_charge_kw": 19.0},
    "Ampd 400": {"charge_kw": 90.0, "standby_kw": 3.0, "fuel_lph_at_charge_kw": 28.5},
    "Custom Solution Req": {"charge_kw": 300.0, "standby_kw": 3.0, "fuel_lph_at_charge_kw": 95.0},
}
CO2_PER_LITER_DIESEL = 2.68
PF = 0.8


def knowledge() -> dict:
    with KNOWLEDGE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def manufacturer_data() -> dict:
    result = {}
    if MANUFACTURER_DIR.exists():
        for path in sorted(MANUFACTURER_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as handle:
                result[path.stem] = json.load(handle)
    return result


def crane_lookup() -> dict[float, float]:
    bands: dict[float, list[float]] = {}
    for data in manufacturer_data().values():
        for group in ("saddle_cranes", "luffing_cranes", "cranes"):
            for row in data.get(group, []):
                kva, peak = row.get("gen_size_kva"), row.get("peak_kw")
                if kva and peak:
                    bands.setdefault(float(kva), []).append(float(peak))
    return {k: round(max(values), 1) for k, values in bands.items()}


def lookup_crane_peak_kw(gen_kva: float) -> float:
    lookup = crane_lookup()
    if not lookup:
        return round(gen_kva * 0.28, 1)
    keys = sorted(lookup)
    if gen_kva <= keys[0]:
        return lookup[keys[0]]
    if gen_kva >= keys[-1]:
        return lookup[keys[-1]]
    lo = max(key for key in keys if key <= gen_kva)
    hi = min(key for key in keys if key >= gen_kva)
    if lo == hi:
        return lookup[lo]
    return round(lookup[lo] + ((gen_kva - lo) / (hi - lo)) * (lookup[hi] - lookup[lo]), 1)


def nearest_generator_size(required_kw: float) -> float:
    minimum = required_kw / PF
    for size in sorted(GEN_RENTAL_PRICES):
        if size >= minimum:
            return float(size)
    return round(minimum, 1)


def generator_rate(kva: float, item: dict) -> float:
    supplied = float(item.get("gen_price") or 0)
    if supplied > 0:
        return supplied
    if int(kva) in GEN_RENTAL_PRICES:
        return float(GEN_RENTAL_PRICES[int(kva)])
    return kva * 1.5


def calculate(data: dict) -> dict:
    project_weeks = float(data.get("weeks", 26))
    site_hours = float(data.get("hours", 50))
    fuel_price = float(data.get("fuel_price", 1.10))
    recharge_source = data.get("recharge_source", "gen")
    electricity_rate = float(data.get("electricity_rate", 0.25))
    items = data.get("items") or []

    base_fuel = base_rental = total_avg = total_peak = total_kwh = 0.0
    breakdown = []
    intermittent_count = 0

    for item in items:
        name = item.get("name", "Unknown")
        item_type = item.get("type", name)
        qty = int(item.get("qty", 1))
        weeks = float(item.get("weeks", project_weeks))
        user_kva = float(item.get("kva") or 0)
        direct_peak = float(item.get("peak_kw") or 0)
        direct_avg = float(item.get("avg_kw") or 0)
        utilisation = float(item.get("utilisation") or 0)
        spec = EQUIPMENT_SPECS.get(name) or EQUIPMENT_SPECS.get(item_type) or {}

        family = next((key for key in DEMAND_FACTORS if key in item_type), None)
        gen_kva = user_kva or float(spec.get("gen_size_kva") or 100)
        if direct_peak > 0:
            peak = direct_peak
        elif spec.get("peak_kw"):
            peak = float(spec["peak_kw"])
        elif family:
            peak = round(gen_kva * DEMAND_FACTORS[family], 1)
        else:
            peak = round(gen_kva * 0.8, 1)
        if family and "crane" in item_type.lower() and not direct_peak and not spec.get("peak_kw"):
            peak = lookup_crane_peak_kw(gen_kva)

        if utilisation > 0:
            average = peak * utilisation / 100
        elif direct_avg > 0:
            average = direct_avg
        else:
            average = float(spec.get("avg_kw") or peak * UTIL_RATES.get(family, 0.30))
        if family and "crane" in item_type.lower():
            idle = 10.0 if gen_kva >= 500 else 7.0 if gen_kva >= 160 else 3.0
            average = max(average, idle)

        fuel_lph = float(spec.get("gen_fuel_lph") or gen_kva * (0.04 + 0.20 * (average / max(gen_kva * PF, 1))))
        run_hours = 168 if "cabin" in name.lower() or "silo" in name.lower() else site_hours
        if run_hours < 168:
            run_hours *= 1.1
        item_fuel = fuel_lph * run_hours * qty * weeks
        base_fuel += item_fuel
        base_rental += generator_rate(gen_kva, item) * qty * weeks
        total_avg += average * qty
        total_peak += peak * qty
        total_kwh += average * qty * run_hours * weeks
        if any(token in item_type.lower() for token in ("crane", "tower", "hoist")):
            intermittent_count += qty
        breakdown.append({"name": name, "qty": qty, "weeks": weeks, "assumed_gen": f"{int(gen_kva)} kVA", "total_fuel": round(item_fuel)})

    baseline_cost = base_fuel * fuel_price + base_rental
    sus_kva = total_avg / PF
    peak_kva = total_peak / PF
    diversity = {1: 1.0, 2: 0.8, 3: 0.65, 4: 0.55}.get(intermittent_count, 0.5 if intermittent_count > 4 else 1.0)
    sus_kva *= diversity
    selected = next((name for name, unit in AMPD_UNITS.items() if sus_kva <= unit["continuous_kva"] and peak_kva <= unit["peak_kva"]), "Custom Solution Req")
    unit_count = 1
    unit = AMPD_UNITS.get(selected, {"continuous_kva": 0, "peak_kva": 0})
    recharge = RECHARGE_GENS[selected]
    standby_kwh = recharge["standby_kw"] * 168 * project_weeks
    if recharge_source == "mains":
        ampd_fuel = 0.0
        ampd_co2 = 0.0
        ampd_recharge_cost = ((total_kwh + standby_kwh) / 0.90) * electricity_rate
        runtime = 0.0
        recharge_label = f"Mains ({electricity_rate:.2f}/kWh)"
    else:
        needed_kwh = (total_kwh + standby_kwh) / 0.90
        runtime_total = needed_kwh / recharge["charge_kw"] if recharge["charge_kw"] else 0
        runtime = runtime_total / project_weeks if project_weeks else 0
        ampd_fuel = runtime_total * recharge["fuel_lph_at_charge_kw"]
        recharge_kva = nearest_generator_size(recharge["charge_kw"])
        ampd_recharge_cost = ampd_fuel * fuel_price + generator_rate(recharge_kva, {}) * project_weeks
        recharge_label = f"{int(recharge_kva)}kVA generator ({recharge['charge_kw']:.0f}kW charge)"
    ampd_cost = AMPD_RATES.get(selected, 0) * unit_count * project_weeks + ampd_recharge_cost
    base_co2 = base_fuel * CO2_PER_LITER_DIESEL
    ampd_co2 = ampd_fuel * CO2_PER_LITER_DIESEL
    fuel_saved = base_fuel - ampd_fuel
    co2_saved = base_co2 - ampd_co2

    return {
        "baseline": {"fuel_liters": round(base_fuel), "co2_tonnes": round(base_co2 / 1000, 1), "cost_total": round(baseline_cost), "breakdown": breakdown, "total_peak_kw": round(total_peak, 1), "total_avg_kw": round(total_avg, 1)},
        "ampd": {"unit_name": selected, "unit_count": unit_count, "weekly_rate": AMPD_RATES.get(selected, 0), "recharge_source": recharge_source, "recharge_label": recharge_label, "recharge_gen": recharge_label.split(" generator")[0] if recharge_source == "gen" else "Mains", "recharge_charge_kw": recharge["charge_kw"], "recharge_standby_kw": recharge["standby_kw"], "recharge_efficiency": 0.90, "recharge_min_generator_kva": round(recharge["charge_kw"] / PF, 1), "runtime_hours_weekly": round(runtime, 1), "fuel_liters": round(ampd_fuel), "co2_tonnes": round(ampd_co2 / 1000, 1), "cost_total": round(ampd_cost), "hire_weeks": round(project_weeks), "is_undersized": runtime > 168, "is_exceeded": selected == "Custom Solution Req"},
        "savings": {"fuel": round(fuel_saved), "co2": round(co2_saved / 1000, 1), "cost": round(baseline_cost - ampd_cost), "trees": int(co2_saved / 20), "moon_trips": round(fuel_saved * 12 / 384400, 2), "car_miles": round(co2_saved / 0.404), "jarvis_insight": "Local Loadout calculation"},
    }


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "loadout-local"})


@app.get("/api/jarvis/loadout-knowledge")
def loadout_knowledge():
    data = knowledge()
    data["runtime_crane_generator_kva_to_peak_kw"] = {str(k): v for k, v in crane_lookup().items()}
    return jsonify(data)


@app.get("/api/manufacturers")
def manufacturers():
    return jsonify(manufacturer_data())


@app.get("/api/data-manifest")
def data_manifest():
    return jsonify({
        "data_dir": str(DATA_DIR),
        "files": sorted(path.name for path in DATA_DIR.iterdir() if path.is_file()),
        "manufacturer_files": sorted(path.name for path in MANUFACTURER_DIR.glob("*.json")),
    })


@app.post("/api/calculate")
def api_calculate():
    return jsonify(calculate(dict(request.get_json(silent=True) or {})))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8020)

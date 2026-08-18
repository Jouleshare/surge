#!/usr/bin/env python3
"""Print current Surge fuel/electricity assumptions for Discord/agent use."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RATES = ROOT / "surge" / "surge_rates.json"


def load_rates(path: Path) -> dict:
    return json.loads(path.read_text())


def available_regions(data: dict) -> list[str]:
    return sorted(k for k, v in data.items() if k != "_meta" and isinstance(v, dict))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", type=Path, default=DEFAULT_RATES)
    ap.add_argument("--region", default="UK", help="Region code from surge_rates.json, e.g. UK, US, AU")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()
    data = load_rates(args.rates)
    valid_regions = available_regions(data)
    region_code = args.region.upper()
    if region_code not in valid_regions:
        result = {
            "error": "unknown_region",
            "region": args.region,
            "available_regions": valid_regions,
        }
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(
                f"Unknown region '{args.region}'. Available regions: {', '.join(valid_regions)}",
                file=sys.stderr,
            )
        return 2

    region = data[region_code]
    fuel_meta = data.get("_meta", {}).get("fuel_price_update", {})
    electricity_meta = data.get("_meta", {}).get("electricity_price_update", {})
    region_notes = data.get("_meta", {}).get("region_notes", {}).get(region_code, [])
    result = {
        "region": region_code,
        "currency": region.get("currency"),
        "currency_code": region.get("currency_code"),
        "diesel_price": region.get("fuel_price"),
        "diesel_display": region.get("fuel_price_display"),
        "electricity_price": region.get("electricity_rate", region.get("mains_price")),
        "electricity_display": region.get("electricity_rate_display"),
        "electricity_benchmarks": region.get("electricity_benchmarks"),
        "bess_rates": region.get("bess_rates", {}),
        "gen_rates": region.get("gen_rates", {}),
        "fuel_last_checked": fuel_meta.get("checked_at"),
        "fuel_events": fuel_meta.get("events", []),
        "electricity_last_checked": electricity_meta.get("checked_at"),
        "electricity_note": electricity_meta.get("note", "Electricity is a screening assumption unless a site tariff is supplied."),
        "region_notes": region_notes,
    }
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    diesel_display = result["diesel_display"] or "not configured"
    diesel_price = result["diesel_price"] if result["diesel_price"] is not None else "not configured"
    electricity_display = result["electricity_display"] or "not configured"
    electricity_price = result["electricity_price"] if result["electricity_price"] is not None else "not configured"
    print(f"{region_code} diesel: {diesel_display} ({diesel_price}/L internal)")
    print(f"{region_code} mains electricity: {electricity_display} ({electricity_price}/kWh internal)")
    latest = next((event for event in result["fuel_events"] if event.get("region") == region_code), None)
    if latest:
        status = latest.get("status") or ("blocked" if latest.get("blocked") else "checked")
        print(f"Diesel update status: {status} | source date: {latest.get('source_date')} | source: {latest.get('source')}")
    if not result["bess_rates"]:
        print("BESS hire rates: not configured for this region; use region-specific/partner rates before quoting.")
    if not result["gen_rates"]:
        print("Generator hire rates: not configured for this region; use region-specific/partner rates before quoting.")
    print(result["electricity_note"])
    benchmarks = result.get("electricity_benchmarks") or {}
    if benchmarks:
        print(
            "Electricity benchmark source: "
            f"{benchmarks.get('source_name', 'benchmark')} | "
            f"{benchmarks.get('source_date', 'unknown date')} | "
            f"{benchmarks.get('source')}"
        )
    for note in region_notes:
        print(f"Note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

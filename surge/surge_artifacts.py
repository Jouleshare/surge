#!/usr/bin/env python3
"""Surge simulation artifacts.

Creates saved simulation bundles for Big Brother Surge:
- PNG screenshot for Discord attachment
- HTML source view
- JSON assumptions/results
- artifacts index entry for later job memory/version lookup

No external chart libraries are required; the HTML uses inline SVG so screenshots
are deterministic and less likely to fail in a headless browser.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ARTIFACT_DIR = Path(os.environ.get(
    "SURGE_ARTIFACT_DIR",
    "/var/lib/surge/artifacts",
))
ARTIFACTS_INDEX = Path(os.environ.get(
    "SURGE_ARTIFACTS_FILE",
    str(ARTIFACT_DIR / "artifacts.json"),
))
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LOADOUT_KNOWLEDGE_PATH = WORKSPACE_ROOT / "data" / "loadout_knowledge.json"
MANUFACTURER_DIRS = [
    WORKSPACE_ROOT / "data" / "manufacturers",
]

AMPD_200 = {
    "name": "Ampd 200",
    "capacity_kwh": 200.0,
    "continuous_kw": 193.0,
    "peak_kw": 292.0,
    "charge_input_kw": 60.0,
}

# Local confirmed/Deploy-style equipment facts we already trust enough for
# commercial screening. Keep source/confidence visible; do not pretend this is
# final electrical design.
KNOWN_PLANT: Dict[str, Dict[str, Any]] = {
    "wk166b": {
        "display": "WOLFF WK166B",
        "type": "tower_crane",
        "rated_kva": 87,
        "peak_kw": 57.4,
        "avg_kw": 5.7,
        "running_current_a": 126,
        "starting_current_a": 186,
        "start_method": "Freq Soft Start",
        "source": "Deploy manufacturer data + Surge measured field evidence",
        "confidence": "local-confirmed; measured-validation benchmark",
        "motor_kw": "Field evidence: UK legacy Ampd telemetry from a 2 x WK166B setup showed max 35.4kW / 162.3A, p95 22.5kW / 92.3A, average 9.30kW / 32.6A during the sampled period. Use as crane load-profile evidence only, not Ampd 200/400 proof.",
    },
    "wolff166b": {
        "alias_for": "wk166b",
    },
    "166b": {
        "alias_for": "wk166b",
    },
    "wk275b": {
        "display": "WOLFF WK275B",
        "type": "tower_crane",
        "rated_kva": 134,
        "peak_kw": 88.4,
        "avg_kw": 8.8,
        "running_current_a": 194,
        "starting_current_a": 258,
        "start_method": "Freq Soft Start",
        "source": "Deploy manufacturer data",
        "confidence": "local-confirmed",
    },
    "wolff275b": {
        "alias_for": "wk275b",
    },
    "275b": {
        "alias_for": "wk275b",
    },
    "wk355b": {
        "display": "WOLFF WK355B",
        "type": "tower_crane",
        "rated_kva": 194,
        "peak_kw": 128.0,
        "avg_kw": 12.8,
        "running_current_a": 280,
        "starting_current_a": 337,
        "start_method": "Star Delta Soft Start",
        "source": "Deploy manufacturer data + Surge measured field evidence",
        "confidence": "local-confirmed; measured-validation benchmark",
        "motor_kw": "Field evidence: UK legacy Ampd telemetry includes a 2 x WK355B measured load profile at max 22.0kW / 229.8A and a WK355B + WK166B grouped profile at max 35.1kW / 207A. Use as crane load-profile evidence only, not Ampd 200 proof.",
    },
    "wolff355b": {
        "alias_for": "wk355b",
    },
    "355b": {
        "alias_for": "wk355b",
    },
    "alimak650": {
        "display": "Alimak Scando 650",
        "type": "hoist",
        "rated_kva": None,
        "peak_kw": 35.0,
        "avg_kw": 12.0,
        "motor_kw": "varies by variant; public examples include 2×11kW FC",
        "start_method": "variant-dependent / often FC/VFD in modern configs",
        "source": "public Alimak/Cramo-style datasheet snippets; variant to confirm",
        "confidence": "screening-estimate",
    },
    "alimak 650": {
        "alias_for": "alimak650",
    },
    "scando650": {
        "alias_for": "alimak650",
    },
}


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "surge-simulation"


def _norm_model(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_loadout_knowledge() -> Dict[str, Any]:
    return json.loads(LOADOUT_KNOWLEDGE_PATH.read_text())


def _interpolate_crane_peak_kw(gen_kva: float) -> float:
    knowledge = _load_loadout_knowledge()
    lookup = {
        float(k): float(v)
        for k, v in knowledge["crane_generator_kva_to_peak_kw"].items()
    }
    keys = sorted(lookup)
    if gen_kva <= keys[0]:
        return lookup[keys[0]]
    if gen_kva >= keys[-1]:
        return lookup[keys[-1]]
    lo = max(k for k in keys if k <= gen_kva)
    hi = min(k for k in keys if k >= gen_kva)
    if lo == hi:
        return lookup[lo]
    t = (gen_kva - lo) / (hi - lo)
    return round(lookup[lo] + t * (lookup[hi] - lookup[lo]), 1)


def _extract_generator_kva(model: str, raw: Optional[Dict[str, Any]]) -> Optional[float]:
    if raw:
        for key in ("generator_kva", "gen_kva", "crane_gen_kva", "gen_size_kva", "min_gen_kva_raw"):
            kva = _to_float(raw.get(key))
            if kva is not None:
                return kva
    match = re.search(r"(\d+(?:\.\d+)?)\s*k\s*v\s*a", model, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _load_manufacturer_index() -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for directory in MANUFACTURER_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            manufacturer = payload.get("manufacturer") or payload.get("_manufacturer") or path.stem
            for bucket in ("saddle_cranes", "luffing_cranes", "hoists", "silos"):
                for row in payload.get(bucket, []):
                    model = str(row.get("model") or "").strip()
                    if not model:
                        continue
                    spec = dict(row)
                    spec["_manufacturer"] = manufacturer
                    spec["_source_file"] = str(path)
                    if bucket == "hoists":
                        spec["_plant_type"] = "hoist"
                    elif bucket == "silos":
                        spec["_plant_type"] = "silo_mixer"
                    else:
                        spec["_plant_type"] = "tower_crane"
                    index.setdefault(_norm_model(model), spec)
                    for alias in row.get("aliases", []):
                        alias_text = str(alias).strip()
                        if alias_text:
                            index.setdefault(_norm_model(alias_text), spec)
    return index


def _manufacturer_spec(model: str) -> Optional[Dict[str, Any]]:
    row = _load_manufacturer_index().get(_norm_model(model))
    if not row:
        return None
    source_file = Path(row.get("_source_file", "")).name or "manufacturer database"
    notes: List[str] = []
    field = row.get("field_evidence") or {}
    if field:
        single = field.get("single_crane_profile", {})
        two_crane = field.get("two_crane_profile", {})
        grouped = field.get("grouped_crane_profile", {})
        notes.append(_public_note(field.get("note")) or "Field evidence exists; use as a measured benchmark only.")
        if two_crane:
            notes.append(
                f"Two-crane benchmark: {_public_benchmark_source(two_crane)} max {two_crane.get('max_output_kw')}kW / {two_crane.get('max_output_current_a')}A."
            )
        if single:
            notes.append(
                f"Single benchmark: {_public_benchmark_source(single)} max {single.get('max_output_kw')}kW / {single.get('max_output_current_a')}A."
            )
        if grouped:
            notes.append(
                f"Grouped benchmark: {_public_benchmark_source(grouped)} max {grouped.get('max_output_kw')}kW / {grouped.get('max_output_current_a')}A."
            )
    return {
        "display": f"{row.get('_manufacturer', '').upper()} {row.get('model', model)}".strip(),
        "type": row.get("_plant_type") or "tower_crane",
        "rated_kva": row.get("rated_kva"),
        "peak_kw": float(row.get("peak_kw") or 0),
        "avg_kw": float(row.get("avg_kw") or 0),
        "running_current_a": row.get("running_current_a"),
        "starting_current_a": row.get("starting_current_a"),
        "start_method": row.get("start_method"),
        "source": f"{row.get('_manufacturer', 'Manufacturer')} manufacturer database ({source_file})",
        "confidence": "manufacturer-database",
        "motor_kw": " ".join(str(n) for n in notes if n) or None,
    }


def _public_benchmark_source(profile: Dict[str, Any]) -> str:
    source = str(profile.get("source") or "").strip()
    if not source:
        return "measured UK field telemetry"
    if "ESN" in source.upper():
        if "2 x WK166B" in source or "2× WK166B" in source:
            return "UK legacy Ampd telemetry from a 2 x WK166B setup"
        if "WK355B" in source and "WK166B" in source:
            return "UK legacy Ampd telemetry from a WK355B + WK166B setup"
        if "WK355B" in source:
            return "UK legacy Ampd telemetry from a WK355B setup"
        return "UK legacy Ampd telemetry from a comparable setup"
    return source


def _public_note(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    cleaned = re.sub(r"\s*Keep ESN/unit IDs internal[^.]*\.", "", str(note))
    cleaned = re.sub(r"\s*Keep unit IDs internal[^.]*\.", "", cleaned)
    return cleaned.strip()


def _evidence_tier(confidence: str, source: str, notes: Optional[str]) -> str:
    basis = " ".join([confidence or "", source or "", notes or ""]).lower()
    if "field evidence" in basis or "measured" in basis or "benchmark" in basis or "telemetry" in basis:
        return "known-data"
    if "manufacturer" in basis or "local-confirmed" in basis:
        return "known-spec"
    if "scenario-supplied" in basis:
        return "scenario-supplied"
    return "screening"


def _public_evidence_statement(item: "PlantItem") -> str:
    if item.evidence_tier == "known-data" and item.notes:
        return item.notes
    if item.evidence_tier == "known-spec":
        return (
            f"{item.display}: matched to manufacturer/spec data. Use the figures as a sizing basis, "
            "then validate start behaviour, protection and actual duty cycle."
        )
    if item.evidence_tier == "scenario-supplied":
        return (
            f"{item.display}: using load figures supplied in the scenario. Treat the plant name and load "
            "as unverified customer/site input until an exact spec sheet, database match, drawing or telemetry confirms it."
        )
    return (
        f"{item.display}: no measured benchmark or exact manufacturer match yet, so Surge is screening "
        "from fallback assumptions rather than claiming proof."
    )


def _validation_questions(item: "PlantItem") -> List[str]:
    if item.evidence_tier == "known-data":
        return [
            "Confirm the site charge source: mains, generator, or no charge period.",
            "Check whether the connected load grouping and simultaneity match the benchmark case.",
            "Validate protection, start behaviour and current peaks before treating this as final design.",
        ]
    if item.evidence_tier in {"known-spec", "scenario-supplied"}:
        return [
            "Confirm the exact model/variant against a manufacturer spec sheet or database record, and whether the quoted figures are nameplate, generator schedule or measured load.",
            "Ask for existing generator size or grid limit to separate peak allowance from real energy use.",
            "Confirm daily operating hours and charge window.",
        ]
    return [
        "What exact plant are we powering: crane model, hoist, welfare, chargers or other loads?",
        "What is the existing generator size or grid/import limit?",
        "Is the site problem peak load, runtime, emissions, noise, grid constraint or fuel cost?",
        "What charge source is available: mains, generator or no charge?",
        "How many hours per day does the load actually operate?",
    ]


def _loadout_fallback_spec(model: str, raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    gen_kva = _extract_generator_kva(model, raw)
    if gen_kva is None:
        return None
    peak_kw = _interpolate_crane_peak_kw(gen_kva)
    utilisation = _load_loadout_knowledge()["default_assumptions"]["crane_utilisation_pct_for_avg"] / 100
    avg_kw = round(peak_kw * utilisation, 1)
    return {
        "display": model,
        "type": "tower_crane",
        "rated_kva": gen_kva,
        "peak_kw": peak_kw,
        "avg_kw": avg_kw,
        "source": "generator-kVA screening assumption",
        "confidence": "loadout-fallback",
        "motor_kw": (
            f"No exact plant match found; estimated from {gen_kva:g}kVA generator band using "
            "screening logic. Generator kVA is not continuous crane draw; confirm drawings and telemetry."
        ),
    }


def _direct_raw_spec(model: str, raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    peak_kw = _to_float(raw.get("peak_kw"))
    if peak_kw is None:
        return None
    avg_kw = _to_float(raw.get("avg_kw"))
    if avg_kw is None:
        avg_kw = round(peak_kw * 0.10, 1)
    return {
        "display": raw.get("display") or model,
        "type": raw.get("type") or "tower_crane",
        "rated_kva": raw.get("rated_kva"),
        "peak_kw": peak_kw,
        "avg_kw": avg_kw,
        "source": raw.get("source") or "scenario supplied load data",
        "confidence": raw.get("confidence") or "scenario-supplied",
        "motor_kw": raw.get("notes") or raw.get("motor_kw"),
    }


def lookup_plant(model: str, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = _norm_model(model)
    data = KNOWN_PLANT.get(key) or KNOWN_PLANT.get(model.lower().strip())
    if data and data.get("alias_for"):
        data = KNOWN_PLANT[data["alias_for"]]
    if data:
        out = dict(data)
        out["model_input"] = model
        return out
    for candidate in (
        _manufacturer_spec(model),
        _direct_raw_spec(model, raw),
        _loadout_fallback_spec(model, raw),
    ):
        if candidate:
            candidate["model_input"] = model
            return candidate
    return {
        "display": model,
        "type": "unknown",
        "rated_kva": None,
        "peak_kw": 60.0,
        "avg_kw": 15.0,
        "source": "fallback screening assumption — save verified spec when found",
        "confidence": "fallback-estimate",
        "model_input": model,
    }


@dataclass
class PlantItem:
    model: str
    qty: int = 1
    display: str = ""
    type: str = "unknown"
    peak_kw: float = 0.0
    avg_kw: float = 0.0
    source: str = ""
    confidence: str = ""
    start_method: Optional[str] = None
    notes: Optional[str] = None
    evidence_tier: str = "screening"
    evidence_statement: str = ""
    validation_questions: List[str] = field(default_factory=list)

    @classmethod
    def from_model(cls, model: str, qty: int = 1, raw: Optional[Dict[str, Any]] = None) -> "PlantItem":
        spec = lookup_plant(model, raw)
        item = cls(
            model=model,
            qty=qty,
            display=spec.get("display") or model,
            type=spec.get("type") or "unknown",
            peak_kw=float(spec.get("peak_kw") or 0.0),
            avg_kw=float(spec.get("avg_kw") or 0.0),
            source=spec.get("source") or "",
            confidence=spec.get("confidence") or "",
            start_method=spec.get("start_method"),
            notes=spec.get("motor_kw"),
        )
        item.evidence_tier = _evidence_tier(item.confidence, item.source, item.notes)
        item.evidence_statement = _public_evidence_statement(item)
        item.validation_questions = _validation_questions(item)
        return item

    @property
    def total_peak_kw(self) -> float:
        return self.peak_kw * self.qty

    @property
    def total_avg_kw(self) -> float:
        return self.avg_kw * self.qty


def _expand_items(raw_items: Iterable[Dict[str, Any]]) -> List[PlantItem]:
    items: List[PlantItem] = []
    for raw in raw_items:
        items.append(PlantItem.from_model(str(raw.get("model") or raw.get("name") or "Unknown plant"), int(raw.get("qty", 1)), raw))
    return items


def _group_evidence_mode(items: List[PlantItem]) -> str:
    tiers = {item.evidence_tier for item in items}
    if "known-data" in tiers:
        return "known-data"
    if tiers & {"known-spec", "scenario-supplied"}:
        return "known-spec"
    return "screening"


def _group_evidence_summary(items: List[PlantItem]) -> List[str]:
    seen = set()
    lines = []
    for item in items:
        line = item.evidence_statement
        if line and line not in seen:
            lines.append(line)
            seen.add(line)
    return lines


def _group_validation_questions(items: List[PlantItem]) -> List[str]:
    seen = set()
    questions = []
    for item in items:
        for question in item.validation_questions or []:
            if question not in seen:
                questions.append(question)
                seen.add(question)
    return questions[:6]


def _daily_profiles(groups: List[Dict[str, Any]], active_start: int, active_hours: int, charge_start: Optional[int], charge_hours: float, charge_kw: float, capacity_kwh: float) -> Dict[str, Any]:
    labels: List[str] = []
    load_kw: List[float] = []
    charge_profile: List[float] = []
    soc_pct: List[float] = []
    soc_kwh = capacity_kwh * 0.80
    active_end = active_start + active_hours
    charge_end = (charge_start or active_end) + charge_hours

    # Use 15-min steps. Active load is intermittent, with deterministic pulses
    # to show crane/hoist peaks without assuming nameplate draw is continuous.
    for step in range(96):
        hour = step / 4.0
        labels.append(f"{int(hour):02d}:{int((hour % 1) * 60):02d}")
        active = active_start <= hour < active_end
        if active:
            base = sum(g["avg_kw"] for g in groups)
            peak_headroom = max(sum(g["peak_kw"] for g in groups) - base, 0)
            wave = max(0.0, math.sin((hour - active_start) * math.pi * 1.35))
            pulse = 1.0 if (step % 13 in (0, 1, 2)) else 0.0
            kw = base + (peak_headroom * 0.42 * wave) + (peak_headroom * 0.58 * pulse)
            kw = min(sum(g["peak_kw"] for g in groups), kw)
            ch = 0.0
        else:
            kw = 0.0
            ch = charge_kw if (charge_start or active_end) <= hour < charge_end else 0.0
        soc_kwh += (ch - kw) * 0.25
        soc_kwh = max(0.0, min(capacity_kwh, soc_kwh))
        load_kw.append(round(kw, 1))
        charge_profile.append(round(ch, 1))
        soc_pct.append(round((soc_kwh / capacity_kwh) * 100, 1))

    return {
        "labels": labels,
        "load_kw": load_kw,
        "charge_kw": charge_profile,
        "soc_pct": soc_pct,
        "peak_load_kw": round(max(load_kw or [0]), 1),
        "daily_load_kwh": round(sum(v * 0.25 for v in load_kw), 1),
        "charge_hours": round(sum(0.25 for v in charge_profile if v > 0), 1),
        "min_soc_pct": round(min(soc_pct or [0]), 1),
    }


def _polyline(values: List[float], width: int, height: int, max_value: float, x0: int, y0: int) -> str:
    if not values:
        return ""
    step = width / max(len(values) - 1, 1)
    pts = []
    for i, val in enumerate(values):
        x = x0 + i * step
        y = y0 + height - (min(val, max_value) / max_value * height if max_value else 0)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _render_html(payload: Dict[str, Any]) -> str:
    profile = payload["profile"]
    title = payload["title"]
    subtitle = payload["subtitle"]
    width, height = 780, 340
    x0, y0 = 60, 42
    max_kw = max(200, math.ceil(profile["peak_load_kw"] / 50) * 50)
    load_line = _polyline(profile["load_kw"], width, height, max_kw, x0, y0)
    charge_line = _polyline(profile["charge_kw"], width, height, max_kw, x0, y0)
    soc_line = _polyline(profile["soc_pct"], width, height, 100, x0, y0)
    hour_ticks = "".join(
        f'<text x="{x0 + (h/24)*width:.0f}" y="{y0+height+26}" fill="#8ea6c5" font-size="11" text-anchor="middle">{h:02d}:00</text>'
        for h in range(0, 25, 4)
    )
    grid = "".join(
        f'<line x1="{x0}" x2="{x0+width}" y1="{y0 + i*height/4:.0f}" y2="{y0 + i*height/4:.0f}" stroke="rgba(255,255,255,.08)" />'
        for i in range(5)
    ) + "".join(
        f'<line x1="{x0 + i*width/6:.0f}" x2="{x0 + i*width/6:.0f}" y1="{y0}" y2="{y0+height}" stroke="rgba(255,255,255,.055)" />'
        for i in range(7)
    )
    mode_labels = {
        "known-data": "Known-data mode",
        "known-spec": "Known-spec mode",
        "scenario-supplied": "Scenario-supplied mode",
        "screening": "Screening mode",
    }
    equipment_html = "".join(
        f"<li><b>{g['label']}</b>: peak ~{g['peak_kw']:.0f}kW, average ~{g['avg_kw']:.1f}kW "
        f"<span>({mode_labels.get(g.get('evidence_mode'), g.get('evidence_mode'))}; {g['confidence']})</span></li>"
        for g in payload["groups"]
    )
    source_values = sorted(set(g.get("source", "") for g in payload["groups"] if g.get("source")))
    # Keep the panel compact: detailed source/caveats live in the JSON artifact.
    sources_html = "".join(f"<li>{src}</li>" for src in source_values[:2])
    if len(source_values) > 2:
        sources_html += f"<li>+{len(source_values)-2} more in JSON artifact</li>"
    evidence_lines = []
    for group in payload["groups"]:
        evidence_lines.extend(group.get("evidence_summary") or [])
    evidence_html = "".join(f"<li>{line}</li>" for line in evidence_lines[:3])
    question_lines = []
    for group in payload["groups"]:
        question_lines.extend(group.get("validation_questions") or [])
    deduped_questions = list(dict.fromkeys(question_lines))[:4]
    questions_html = "".join(f"<li>{line}</li>" for line in deduped_questions)
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#07101d;color:#e5f0ff;}}
.page{{width:1280px;height:720px;box-sizing:border-box;padding:34px 42px;background:linear-gradient(135deg,#07101d 0%,#0b1729 55%,#10243a 100%);position:relative;}}
h1{{margin:0;font-size:31px;letter-spacing:-.03em;}}.sub{{color:#9fb3cc;margin-top:6px;font-size:15px;}}
.top{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px;}}.badge{{background:#163d2a;color:#82f6b1;border:1px solid rgba(130,246,177,.35);padding:10px 14px;border-radius:999px;font-weight:850;}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px;}}.card{{background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.11);border-radius:16px;padding:14px 16px;}}
.label{{color:#98aac2;font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;}}.value{{margin-top:5px;font-size:25px;font-weight:900;}}
.grid{{display:grid;grid-template-columns:1.45fr .8fr;gap:20px;}}.panel{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:16px;}}
.notes{{font-size:12px;line-height:1.24;color:#c8d7ea;}}.notes b{{color:#fff;}}.notes ul{{margin:6px 0 8px 17px;padding:0;}}.notes li{{margin-bottom:4px;}}.notes span{{color:#8ea6c5;}}
.warn{{margin-top:8px;padding:9px 11px;border-radius:12px;background:rgba(250,204,21,.1);border:1px solid rgba(250,204,21,.28);color:#fde68a;font-size:11px;line-height:1.25;}}
.foot{{position:absolute;bottom:14px;left:42px;right:42px;color:#7790ad;font-size:11px;display:flex;justify-content:space-between;}}
</style></head><body><div class="page">
<div class="top"><div><h1>{title}</h1><div class="sub">{subtitle}</div></div><div class="badge">Commercial screen · attachable artifact</div></div>
<div class="cards">
<div class="card"><div class="label">Peak combined load</div><div class="value">~{profile['peak_load_kw']:.0f} kW</div></div>
<div class="card"><div class="label">Daily load energy</div><div class="value">~{profile['daily_load_kwh']:.0f} kWh</div></div>
<div class="card"><div class="label">Charge runtime</div><div class="value">~{profile['charge_hours']:.0f} h/day</div></div>
<div class="card"><div class="label">Minimum Ampd SOC</div><div class="value">~{profile['min_soc_pct']:.0f}%</div></div>
</div>
<div class="grid"><div class="panel">
<svg width="900" height="420" viewBox="0 0 900 420" xmlns="http://www.w3.org/2000/svg">
{grid}
<text x="24" y="{y0+height}" fill="#8ea6c5" font-size="11">0</text>
<text x="18" y="{y0+height/2:.0f}" fill="#8ea6c5" font-size="11">{max_kw/2:.0f}</text>
<text x="12" y="{y0+4}" fill="#8ea6c5" font-size="11">{max_kw:.0f}</text>
<polyline points="{load_line}" fill="none" stroke="#60a5fa" stroke-width="3"/>
<polyline points="{charge_line}" fill="none" stroke="#fbbf24" stroke-width="3" stroke-dasharray="7 5"/>
<polyline points="{soc_line}" fill="none" stroke="#4ade80" stroke-width="3"/>
<text x="60" y="24" fill="#dbeafe" font-weight="800" font-size="13">Load kW / charge kW / SOC %</text>
{hour_ticks}
<circle cx="590" cy="22" r="5" fill="#60a5fa"/><text x="602" y="26" fill="#cfe3ff" font-size="12">Load</text>
<circle cx="655" cy="22" r="5" fill="#fbbf24"/><text x="667" y="26" fill="#cfe3ff" font-size="12">Charge</text>
<circle cx="742" cy="22" r="5" fill="#4ade80"/><text x="754" y="26" fill="#cfe3ff" font-size="12">SOC</text>
</svg></div>
<div class="panel notes"><b>Equipment grouping</b><ul>{equipment_html}</ul><b>Evidence basis</b><ul>{sources_html}</ul><b>Interpretation</b><ul>{evidence_html}</ul><b>Validation questions</b><ul>{questions_html}</ul><div class="warn">Subject to electrical validation: protection, start behaviour, board grouping, charge source and measured diversity.</div></div></div>
<div class="foot"><span>Surge by Ampd Energy · generated {payload['generated_at']}</span><span>Paths and detailed assumptions saved in JSON artifact</span></div>
</div></body></html>'''


def _capture_png(html_path: Path, png_path: Path, timeout_ms: int = 15000) -> None:
    subprocess.run(
        ["playwright", "screenshot", f"--timeout={timeout_ms}", f"file://{html_path}", str(png_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _read_index() -> List[Dict[str, Any]]:
    if ARTIFACTS_INDEX.exists():
        try:
            return json.loads(ARTIFACTS_INDEX.read_text())
        except Exception:
            return []
    return []


def _write_index(entries: List[Dict[str, Any]]) -> None:
    ARTIFACTS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARTIFACTS_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2))
    tmp.replace(ARTIFACTS_INDEX)


def generate_artifact(scenario: Dict[str, Any]) -> Dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    title = scenario.get("title") or "Surge 24-hour simulation"
    active_start = int(scenario.get("active_start", 7))
    active_hours = int(scenario.get("active_hours", 10))
    charge_start = scenario.get("charge_start", active_start + active_hours)
    charge_hours = float(scenario.get("charge_hours", 5))
    charge_kw = float(scenario.get("charge_kw", AMPD_200["charge_input_kw"]))
    capacity = float(scenario.get("capacity_kwh", AMPD_200["capacity_kwh"]))

    groups: List[Dict[str, Any]] = []
    for idx, group in enumerate(scenario.get("groups", []), start=1):
        items = _expand_items(group.get("items", []))
        label = group.get("label") or " + ".join(f"{i.qty}× {i.display}" if i.qty > 1 else i.display for i in items) or f"Group {idx}"
        groups.append({
            "label": label,
            "items": [asdict(i) for i in items],
            "peak_kw": sum(i.total_peak_kw for i in items),
            "avg_kw": sum(i.total_avg_kw for i in items),
            "source": "; ".join(sorted(set(i.source for i in items if i.source))),
            "confidence": ", ".join(sorted(set(i.confidence for i in items if i.confidence))),
            "evidence_mode": _group_evidence_mode(items),
            "evidence_summary": _group_evidence_summary(items),
            "validation_questions": _group_validation_questions(items),
        })
    if not groups:
        raise ValueError("scenario must include at least one group with items")

    profile = _daily_profiles(groups, active_start, active_hours, charge_start, charge_hours, charge_kw, capacity)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    artifact_id = scenario.get("artifact_id") or f"surge-{stamp}-{_slug(title)[:48]}"
    base = ARTIFACT_DIR / artifact_id
    payload = {
        "artifact_id": artifact_id,
        "created_at": datetime.utcnow().isoformat(),
        "generated_at": datetime.utcnow().strftime("%d %b %Y %H:%M UTC"),
        "job_id": scenario.get("job_id"),
        "title": title,
        "subtitle": scenario.get("subtitle") or f"{active_hours} active hours/day · {AMPD_200['name']} · {charge_kw:.0f}kW trickle-charge",
        "scenario": scenario,
        "ampd": dict(AMPD_200),
        "groups": groups,
        "profile": profile,
        "notes": scenario.get("notes", []),
        "evidence_modes": sorted(set(g["evidence_mode"] for g in groups)),
        "email_fallback": "If Discord attachment fails, offer to email this artifact after Tom confirms recipient and approval.",
    }
    html_path = base.with_suffix(".html")
    png_path = base.with_suffix(".png")
    json_path = base.with_suffix(".json")
    html_path.write_text(_render_html(payload))
    json_path.write_text(json.dumps(payload, indent=2))
    _capture_png(html_path, png_path)
    payload["paths"] = {
        "html": str(html_path),
        "png": str(png_path),
        "json": str(json_path),
    }
    json_path.write_text(json.dumps(payload, indent=2))
    entries = _read_index()
    entries.append({
        "artifact_id": artifact_id,
        "created_at": payload["created_at"],
        "job_id": payload.get("job_id"),
        "title": title,
        "paths": payload["paths"],
        "summary": {
            "peak_load_kw": profile["peak_load_kw"],
            "daily_load_kwh": profile["daily_load_kwh"],
            "min_soc_pct": profile["min_soc_pct"],
            "groups": [g["label"] for g in groups],
            "evidence_modes": sorted(set(g["evidence_mode"] for g in groups)),
        },
    })
    _write_index(entries)
    return payload


LONDON_2_UNIT_SCENARIO = {
    "title": "London job — 2-unit Ampd 200 optimisation",
    "subtitle": "Unit 1: 2× WK166B · Unit 2: WK275B + Alimak 650 · 10 active hours/day",
    "active_start": 7,
    "active_hours": 10,
    "charge_start": 17,
    "charge_hours": 5,
    "groups": [
        {"label": "Ampd 200 #1 — 2× WK166B tower cranes", "items": [{"model": "WK166B", "qty": 2}]},
        {"label": "Ampd 200 #2 — WK275B + Alimak 650 hoist", "items": [{"model": "WK275B", "qty": 1}, {"model": "Alimak 650", "qty": 1}]},
    ],
    "notes": [
        "Optimised commercial screen assumes electrical grouping and diversity are acceptable.",
        "Conservative fallback is 3× Ampd 200 if hoist start behaviour or board arrangement prevents grouping.",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a saved Surge simulation artifact.")
    parser.add_argument("--scenario", help="Path to scenario JSON. If omitted, use --preset.")
    parser.add_argument("--preset", default="london-2-unit", choices=["london-2-unit"], help="Built-in scenario preset")
    parser.add_argument("--job-id", help="Optional job id to link in artifact memory")
    parser.add_argument("--discord-reply", action="store_true", help="Print a Discord-safe reply with MEDIA line")
    args = parser.parse_args()

    if args.scenario:
        scenario = json.loads(Path(args.scenario).read_text())
    else:
        scenario = dict(LONDON_2_UNIT_SCENARIO)
    if args.job_id:
        scenario["job_id"] = args.job_id

    artifact = generate_artifact(scenario)
    png = artifact["paths"]["png"]
    if args.discord_reply:
        print("Generated the simulation artifact and attached it below. If Discord fails to show the image, I can email it over after Tom confirms the recipient.")
        print(f"MEDIA:{png}")
    else:
        print(json.dumps(artifact, indent=2))


if __name__ == "__main__":
    main()

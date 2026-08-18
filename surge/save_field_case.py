#!/usr/bin/env python3
"""Append a Surge field evidence case to the configured runtime evidence file.

Usage example:
python3 surge/save_field_case.py --site "London site" --region "London, UK" \
  --ampd-setup "1 x Ampd 200" --powered "2 x WK275B tower cranes" \
  --charge-source "60kVA Stage V generator" --result "Worked in live site conditions" \
  --source "Tom Carter confirmation" --status verified_by_tom --confidence high
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get("SURGE_FIELD_EVIDENCE_FILE", "/var/lib/surge/field_evidence/surge_field_cases.json"))


def slugify(text):
    text = (text or "field-case").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or "field-case"


def split_multi(values):
    out = []
    for value in values or []:
        for part in value.split(";"):
            part = part.strip()
            if part:
                out.append(part)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site")
    ap.add_argument("--region")
    ap.add_argument("--date-or-period")
    ap.add_argument("--ampd-setup", required=True)
    ap.add_argument("--powered", action="append", default=[])
    ap.add_argument("--plant-model", action="append", default=[])
    ap.add_argument("--charge-source")
    ap.add_argument("--distribution-grouping")
    ap.add_argument("--working-hours")
    ap.add_argument("--result", required=True)
    ap.add_argument("--issue", action="append", default=[])
    ap.add_argument("--caveat", action="append", default=[])
    ap.add_argument("--source", required=True)
    ap.add_argument("--evidence", action="append", default=[])
    ap.add_argument("--commercial-note", action="append", default=[])
    ap.add_argument("--status", default="verified_by_tom", choices=["claimed", "verified_by_tom", "documented", "telemetry_backed"])
    ap.add_argument("--confidence", default="medium", choices=["low", "medium", "high", "very_high"])
    args = ap.parse_args()

    STORE.parent.mkdir(parents=True, exist_ok=True)
    if STORE.exists():
        data = json.loads(STORE.read_text())
    else:
        data = {"last_updated": None, "cases": []}
    now = datetime.now(timezone.utc).isoformat()
    base = f"{args.site or args.region or 'case'}-{args.ampd_setup}-{','.join(args.powered) or args.result}"
    case = {
        "id": f"field-case-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{slugify(base)}",
        "status": args.status,
        "confidence": args.confidence,
        "site": args.site,
        "region": args.region,
        "date_or_period": args.date_or_period,
        "ampd_setup": args.ampd_setup,
        "powered": split_multi(args.powered),
        "plant_models": split_multi(args.plant_model),
        "charge_source": args.charge_source,
        "distribution_grouping": args.distribution_grouping,
        "working_hours": args.working_hours,
        "result": args.result,
        "issues": split_multi(args.issue),
        "caveats": split_multi(args.caveat),
        "source": args.source,
        "evidence_links_or_files": split_multi(args.evidence),
        "commercial_notes": split_multi(args.commercial_note),
        "created_at": now,
        "updated_at": now,
    }
    existing = {c.get("id") for c in data.get("cases", [])}
    original_id = case["id"]
    i = 2
    while case["id"] in existing:
        case["id"] = f"{original_id}-{i}"
        i += 1
    data.setdefault("cases", []).append(case)
    data["last_updated"] = now[:10]
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(case, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

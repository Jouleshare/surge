#!/usr/bin/env python3
"""Update Surge diesel assumptions from source-backed benchmark data.

Sources:
- UK: GOV.UK / DESNZ weekly road fuel prices CSV (ULSD pence/litre)
- US: EIA weekly U.S. No 2 Diesel Retail Prices page (dollars/gallon)
- AU: GlobalPetrolPrices Australia diesel page (third-party benchmark, AUD/litre)

By default this is a dry run. Use --apply to write surge_rates.json.
Large moves are blocked unless --force is supplied.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

GOV_UK_PAGE = "https://www.gov.uk/government/statistics/weekly-road-fuel-prices"
EIA_DIESEL_PAGE = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=pet&s=EMD_EPD2D_PTE_NUS_DPG&f=W"
GLOBALPETROLPRICES_AU_DIESEL_PAGE = "https://www.globalpetrolprices.com/Australia/diesel_prices/"
LITRES_PER_US_GALLON = 3.785411784
DEFAULT_RATES_PATH = Path(__file__).resolve().parent / "surge_rates.json"


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "SurgeFuelUpdater/1.0 (+benchmark data fetch)"})
    with urlopen(req, timeout=25) as resp:
        raw = resp.read()
    return raw.decode("utf-8-sig", errors="replace")


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "SurgeFuelUpdater/1.0 (+benchmark data fetch)"})
    with urlopen(req, timeout=25) as resp:
        return resp.read()


def latest_uk_diesel():
    page = fetch_text(GOV_UK_PAGE)
    match = re.search(r'https://assets\.publishing\.service\.gov\.uk/[^"<>]+weekly_road_fuel_prices_[^"<>]+\.csv', page)
    if not match:
        raise RuntimeError("Could not find GOV.UK weekly road fuel CSV link")
    csv_url = match.group(0)
    text = fetch_bytes(csv_url).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise RuntimeError("GOV.UK fuel CSV contained no rows")
    row = rows[-1]
    date = row.get("Date") or ""
    diesel_col = next((k for k in row if "ULSD" in k and "Pump price" in k), None)
    if not diesel_col:
        raise RuntimeError("Could not find ULSD pump price column in GOV.UK CSV")
    pence_per_litre = float(row[diesel_col])
    return {
        "region": "UK",
        "price": round(pence_per_litre / 100, 4),
        "display": f"£{pence_per_litre / 100:.2f}/L",
        "source": GOV_UK_PAGE,
        "source_data": csv_url,
        "source_date": date,
        "raw_unit": "pence_per_litre",
        "raw_value": pence_per_litre,
    }


def latest_us_diesel():
    raw = fetch_text(EIA_DIESEL_PAGE)
    # Rows are grouped by month with alternating date/value cells. Extract all date/value pairs.
    pairs = []
    row_re = re.compile(r"<tr>\s*<td class='B6'>&nbsp;&nbsp;(\d{4})-([A-Za-z]{3})</td>(.*?)</tr>", re.S)
    cell_re = re.compile(r"<td class='B5'>(.*?)</td>\s*<td class='B3'>(.*?)</td>", re.S)
    for year, month, body in row_re.findall(raw):
        for date_cell, value_cell in cell_re.findall(body):
            date_text = html.unescape(re.sub(r"<.*?>", "", date_cell)).replace("\xa0", " ").strip()
            value_text = html.unescape(re.sub(r"<.*?>", "", value_cell)).replace("\xa0", " ").strip()
            if not date_text or not value_text or value_text in {"-", "--", "NA", "W"}:
                continue
            try:
                mm, dd = [int(x) for x in date_text.split("/")]
                value = float(value_text)
            except Exception:
                continue
            iso_date = f"{int(year):04d}-{mm:02d}-{dd:02d}"
            pairs.append((iso_date, value))
    if not pairs:
        raise RuntimeError("Could not parse EIA diesel price table")
    source_date, dollars_per_gallon = pairs[-1]
    dollars_per_litre = dollars_per_gallon / LITRES_PER_US_GALLON
    return {
        "region": "US",
        "price": round(dollars_per_litre, 4),
        "display": f"${dollars_per_gallon:.2f}/gal",
        "source": EIA_DIESEL_PAGE,
        "source_date": source_date,
        "raw_unit": "dollars_per_gallon",
        "raw_value": dollars_per_gallon,
    }


def manual_region(region: str, note: str):
    return {
        "region": region,
        "status": "manual",
        "message": note,
        "source": None,
        "source_date": None,
    }


def error_region(region: str, message: str, source: str | None = None):
    return {
        "region": region,
        "status": "error",
        "message": message,
        "source": source,
        "source_date": None,
    }


def latest_au_diesel():
    raw = fetch_text(GLOBALPETROLPRICES_AU_DIESEL_PAGE)
    text = html.unescape(re.sub(r"<.*?>", " ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    match = re.search(
        r"current price of diesel fuel in Australia is AUD\s+([0-9]+(?:\.[0-9]+)?)\s+per liter"
        r"\s+or USD\s+([0-9]+(?:\.[0-9]+)?)\s+per liter\s+based on the latest update from\s+([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})",
        text,
        re.I,
    )
    if not match:
        raise RuntimeError("Could not parse GlobalPetrolPrices AU current diesel sentence")
    aud_per_litre = float(match.group(1))
    usd_per_litre = float(match.group(2))
    source_date = match.group(3)
    return {
        "region": "AU",
        "price": round(aud_per_litre, 4),
        "display": f"A${aud_per_litre:.2f}/L",
        "source": GLOBALPETROLPRICES_AU_DIESEL_PAGE,
        "source_date": source_date,
        "raw_unit": "AUD_per_litre",
        "raw_value": aud_per_litre,
        "third_party_benchmark": True,
        "comparison_usd_per_litre": usd_per_litre,
    }


FUEL_UPDATERS = {
    "UK": latest_uk_diesel,
    "US": latest_us_diesel,
    "AU": latest_au_diesel,
}

DEFAULT_UPDATE_REGIONS = ("UK", "US", "AU")


def pct_change(old: float, new: float) -> float:
    if not old:
        return 0.0
    return (new - old) / old


def load_rates(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def resolve_regions(args, rates: dict, parser: argparse.ArgumentParser) -> list[str]:
    if args.uk_only or args.us_only:
        if args.region or args.all:
            parser.error("--uk-only/--us-only cannot be combined with --region or --all")
        return ["UK"] if args.uk_only else ["US"]
    if args.all:
        if args.region:
            parser.error("--all cannot be combined with --region")
        return sorted(k for k in rates if k != "_meta" and isinstance(rates[k], dict))
    if args.region:
        seen = []
        for region in args.region:
            code = region.upper()
            if code not in seen:
                seen.append(code)
        return seen
    return list(DEFAULT_UPDATE_REGIONS)


def collect_updates(regions: list[str], rates: dict, parser: argparse.ArgumentParser) -> dict:
    updates = {}
    for region in regions:
        if region not in rates or not isinstance(rates[region], dict):
            available = sorted(k for k in rates if k != "_meta" and isinstance(rates[k], dict))
            parser.error(f"Region {region} is not configured in surge_rates.json. Available regions: {', '.join(available)}")
        updater = FUEL_UPDATERS.get(region)
        if not updater:
            updates[region] = manual_region(
                region,
                "No automatic diesel updater registered for this region; keep manual/screening fuel_price or add an updater.",
            )
            continue
        try:
            updates[region] = updater()
        except Exception as exc:
            source = None
            if region == "AU":
                source = GLOBALPETROLPRICES_AU_DIESEL_PAGE
            elif region == "UK":
                source = GOV_UK_PAGE
            elif region == "US":
                source = EIA_DIESEL_PAGE
            updates[region] = error_region(region, str(exc), source)
    return updates


def apply_updates(rates: dict, updates: dict, max_change: float, force: bool):
    changed = False
    events = []
    for region, update in updates.items():
        if update.get("status") == "manual" or "price" not in update:
            status = update.get("status", "manual")
            events.append({
                "region": region,
                "old": rates.get(region, {}).get("fuel_price"),
                "new": rates.get(region, {}).get("fuel_price"),
                "display": rates.get(region, {}).get("fuel_price_display"),
                "change_pct": 0.0,
                "blocked": status == "error",
                "status": status,
                "message": update.get("message", "No automatic updater configured"),
                "source_date": update.get("source_date"),
                "source": update.get("source"),
            })
            continue
        current = float(rates[region]["fuel_price"])
        new = float(update["price"])
        change = pct_change(current, new)
        blocked = abs(change) > max_change and not force
        events.append({
            "region": region,
            "old": current,
            "new": new,
            "display": update["display"],
            "change_pct": round(change * 100, 2),
            "blocked": blocked,
            "status": "blocked" if blocked else "checked",
            "source_date": update.get("source_date"),
            "source": update.get("source"),
            "third_party_benchmark": bool(update.get("third_party_benchmark")),
        })
        if blocked:
            continue
        if round(current, 4) != round(new, 4) or rates[region].get("fuel_price_display") != update["display"]:
            rates[region]["fuel_price"] = round(new, 4)
            rates[region]["fuel_price_display"] = update["display"]
            changed = True
    rates.setdefault("_meta", {})["fuel_price_update"] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "max_change_pct_without_force": round(max_change * 100, 2),
        "events": events,
    }
    return changed, events


def maybe_restart(service: str):
    if not service:
        return
    subprocess.run(["systemctl", "restart", service], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Update Surge diesel prices from source-backed benchmark data")
    parser.add_argument("--rates", type=Path, default=DEFAULT_RATES_PATH)
    parser.add_argument("--apply", action="store_true", help="write changes to surge_rates.json")
    parser.add_argument("--force", action="store_true", help="allow large moves beyond --max-change")
    parser.add_argument("--max-change", type=float, default=0.15, help="max fractional change before blocking, default 0.15")
    parser.add_argument("--restart-service", default="", help="systemd service to restart after an applied change")
    parser.add_argument("--region", action="append", help="region code to update; may be supplied multiple times")
    parser.add_argument("--all", action="store_true", help="process all configured regions")
    parser.add_argument("--uk-only", action="store_true", help="legacy alias for --region UK")
    parser.add_argument("--us-only", action="store_true", help="legacy alias for --region US")
    args = parser.parse_args(argv)

    if args.uk_only and args.us_only:
        parser.error("--uk-only and --us-only cannot both be used")

    rates = load_rates(args.rates)
    regions = resolve_regions(args, rates, parser)
    updates = collect_updates(regions, rates, parser)

    changed, events = apply_updates(rates, updates, args.max_change, args.force)
    for event in events:
        if event.get("status") == "manual":
            print(f"MANUAL {event['region']}: {event.get('message')} Current={event.get('display')}")
            continue
        if event.get("status") == "error":
            print(f"ERROR {event['region']}: {event.get('message')} source={event.get('source')}", file=sys.stderr)
            continue
        status = "BLOCKED" if event["blocked"] else ("CHANGE" if round(event["old"], 4) != round(event["new"], 4) else "OK")
        print(f"{status} {event['region']}: {event['old']:.4f} -> {event['new']:.4f} ({event['change_pct']:+.2f}%) {event['display']} source_date={event['source_date']}")

    blocked = [e for e in events if e["blocked"]]
    if blocked:
        print("One or more updates blocked by guardrail; rerun with --force after review if intended.", file=sys.stderr)

    if args.apply:
        write_json_atomic(args.rates, rates)
        if changed:
            maybe_restart(args.restart_service)
            print(f"Applied updates to {args.rates}")
        else:
            print("No applied price changes")
    else:
        print("Dry run only; use --apply to write changes")

    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())

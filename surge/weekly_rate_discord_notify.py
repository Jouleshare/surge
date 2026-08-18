#!/usr/bin/env python3
"""Weekly Surge rate updater + Discord notifier.

Runs source-backed diesel updates once, writes surge_rates.json, then posts
region-specific summaries to the relevant Surge Discord channels.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import update_fuel_prices


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RATES = ROOT / "surge" / "surge_rates.json"
LOG_DIR = Path(os.environ.get("SURGE_RATE_LOG_DIR", "/var/lib/surge/rate-updates"))

CHANNELS = {
    "UK": {
        "channel_id": "1517536800128897105",
        "label": "UK",
    },
    "AU": {
        "channel_id": "1517467045547999443",
        "label": "AU",
    },
    "US": {
        "channel_id": "1517539533946622012",
        "label": "US",
    },
}


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def load_discord_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN is not configured")
    return token


def post_discord(token: str, channel_id: str, content: str) -> dict:
    req = Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "SurgeRateNotifier/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            return {"ok": True, "status": resp.status, "body": json.loads(raw) if raw else None}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = raw
        return {"ok": False, "status": exc.code, "body": body}


def money_change(event: dict) -> str:
    old = event.get("old")
    new = event.get("new")
    if old is None or new is None:
        return ""
    try:
        old_f = float(old)
        new_f = float(new)
    except (TypeError, ValueError):
        return ""
    if round(old_f, 4) == round(new_f, 4):
        return "no change"
    arrow = "up" if new_f > old_f else "down"
    pct = event.get("change_pct")
    if pct is None:
        return arrow
    return f"{arrow} {abs(float(pct)):.2f}%"


def event_for(events: list[dict], region: str) -> dict | None:
    return next((event for event in events if event.get("region") == region), None)


def electricity_line(region: str, rates: dict) -> str:
    cfg = rates.get(region, {})
    display = cfg.get("electricity_rate_display")
    benchmarks = cfg.get("electricity_benchmarks") or {}
    if display and benchmarks:
        source_name = benchmarks.get("source_name") or "electricity benchmark"
        source_date = benchmarks.get("source_date") or "unknown date"
        return f"Electricity: {display}; source {source_name}, {source_date}. Site tariff overrides."
    if display:
        return f"Electricity: {display}; screening assumption. Site tariff overrides."
    return "Electricity: not configured; site tariff required before quoting."


def build_message(region: str, rates: dict, event: dict, checked_at: str) -> str:
    cfg = rates.get(region, {})
    label = CHANNELS[region]["label"]
    status = event.get("status", "checked")
    display = event.get("display") or cfg.get("fuel_price_display", "not configured")
    source_date = event.get("source_date") or "unknown date"
    source = event.get("source") or "source unavailable"
    change = money_change(event)
    third_party = bool(event.get("third_party_benchmark"))
    source_type = "third-party benchmark" if third_party else "source-backed benchmark"

    lines = [
        f"Rates checked - {label}",
        f"Diesel: {display} ({change})",
        f"Source: {source_type}; date {source_date}",
        f"<{source}>",
        electricity_line(region, rates),
        "Use for first-pass screening only. Site/customer/partner rates override.",
    ]
    if status == "blocked":
        lines.insert(1, "Status: blocked by movement guardrail - review before using updated value.")
    elif status == "error":
        lines.insert(1, f"Status: source check failed - {event.get('message', 'unknown error')}")
    lines.append(f"Checked at: {checked_at}")
    return "\n".join(lines)


def update_rates(path: Path, apply: bool) -> tuple[dict, list[dict], bool]:
    rates = update_fuel_prices.load_rates(path)
    regions = list(update_fuel_prices.DEFAULT_UPDATE_REGIONS)
    updates = update_fuel_prices.collect_updates(regions, rates, argparse.ArgumentParser())
    changed, events = update_fuel_prices.apply_updates(rates, updates, max_change=0.15, force=False)
    if apply:
        write_json_atomic(path, rates)
    return rates, events, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update Surge rates and post weekly Discord summaries")
    parser.add_argument("--rates", type=Path, default=DEFAULT_RATES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--regions", nargs="*", default=["UK", "AU", "US"], choices=sorted(CHANNELS))
    args = parser.parse_args(argv)

    rates, events, changed = update_rates(args.rates, apply=not args.dry_run)
    checked_at = rates.get("_meta", {}).get("fuel_price_update", {}).get("checked_at") or datetime.now(timezone.utc).isoformat()

    messages = {}
    for region in args.regions:
        event = event_for(events, region)
        if not event:
            continue
        messages[region] = build_message(region, rates, event, checked_at)

    result = {
        "checked_at": checked_at,
        "changed": changed,
        "regions": args.regions,
        "events": events,
        "dry_run": args.dry_run,
        "posts": {},
    }

    if args.dry_run:
        for region, content in messages.items():
            print(f"--- {region} ---\n{content}\n")
            result["posts"][region] = {"ok": True, "dry_run": True}
    else:
        token = load_discord_token()
        for region, content in messages.items():
            channel_id = CHANNELS[region]["channel_id"]
            result["posts"][region] = post_discord(token, channel_id, content)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"{stamp}.json"
    log_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {log_path}")

    failed = [region for region, post in result["posts"].items() if not post.get("ok")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Capture a Loadout/Simulate page screenshot for a Surge job note.

This intentionally shells out to the local Playwright CLI so Surge can use the
browser automation already installed on the Mac without adding Python deps.
"""
import argparse
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

DEFAULT_DIR = Path(os.environ.get("SURGE_SCREENSHOT_DIR", "/var/lib/surge/screenshots"))
SAFE_NAME = re.compile(r"[^a-zA-Z0-9_.-]+")


def safe_filename(value: str) -> str:
    value = SAFE_NAME.sub("-", value.strip()).strip("-._")
    return value or "loadout"


def capture(url: str, output: Optional[str] = None, timeout_ms: int = 15000) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must start with http:// or https://")
    if output:
        out = Path(output)
    else:
        DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
        host = safe_filename(parsed.netloc or "loadout")
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        out = DEFAULT_DIR / f"{host}-{stamp}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["playwright", "screenshot", f"--timeout={timeout_ms}", url, str(out)],
        check=True,
    )
    return out


def main():
    parser = argparse.ArgumentParser(description="Capture a Loadout/Simulate screenshot for Surge.")
    parser.add_argument("url", help="Loadout/Simulate URL to capture")
    parser.add_argument("--output", "-o", help="Output PNG path")
    parser.add_argument("--timeout-ms", type=int, default=15000)
    args = parser.parse_args()
    out = capture(args.url, args.output, args.timeout_ms)
    print(out)


if __name__ == "__main__":
    main()

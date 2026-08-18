import re
import json
import os
import html
import threading
import requests
from datetime import datetime
from collections import Counter
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, Response, render_template
from markdown import markdown

app = Flask(__name__)

# ─── Meta Cloud API Config ────────────────────────────────────────────────────
META_PHONE_NUMBER_ID  = os.environ.get("META_PHONE_NUMBER_ID", "")
META_ACCESS_TOKEN     = os.environ.get("META_ACCESS_TOKEN", "")
META_VERIFY_TOKEN     = os.environ.get("META_VERIFY_TOKEN", "")

# Single source of truth — all rates & specs live in Loadout
LOADOUT_API = "https://loadout.getjoule.co.uk/api/calculate"

# ── Regional config ───────────────────────────────────────────────────────────
# Rates loaded from surge_rates.json (edit that file to update prices, not this code)
_RATES_FILE = os.path.join(os.path.dirname(__file__), "surge_rates.json")
_DATA_DIR = os.environ.get(
    "SURGE_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
)
_LOADOUT_KNOWLEDGE_FILE = os.path.join(_DATA_DIR, "loadout_knowledge.json")
_FIELD_EVIDENCE_FILES = [
    os.path.join(_DATA_DIR, "field_evidence", "surge_field_cases.json"),
]
_LOCAL_MANUFACTURER_DIR = os.path.join(_DATA_DIR, "manufacturers")

def _load_rates():
    """Load regional rate config from surge_rates.json, fall back to defaults."""
    try:
        with open(_RATES_FILE) as f:
            raw = json.load(f)
        # Convert gen_rates keys back to int
        for region in raw.values():
            if "gen_rates" in region:
                region["gen_rates"] = {int(k): v for k, v in region["gen_rates"].items()}
        print(f"[Surge] Loaded rates from {_RATES_FILE}", flush=True)
        return raw
    except Exception as e:
        print(f"[Surge] Could not load surge_rates.json ({e}) — using hardcoded defaults", flush=True)
        return {}

RATES_CONFIG = _load_rates()

UK_CONFIG = RATES_CONFIG.get("UK") or {
    "currency": "£",
    "currency_code": "GBP",
    "fuel_price": 1.50,
    "fuel_price_display": "£1.50/L",
    "bess_rates": {"Ampd 200": 1200, "Ampd 400": 2000},
    "gen_rates": {50: 200, 100: 280, 150: 350, 200: 420, 250: 490, 300: 560, 400: 680, 500: 820},
}

US_CONFIG = RATES_CONFIG.get("US") or {
    "currency": "$",
    "currency_code": "USD",
    "fuel_price": 1.321,
    "fuel_price_display": "$5.00/gal",
    "bess_rates": {"Ampd 200": 2300, "Ampd 400": 3000},
    "gen_rates": {100: 625, 200: 875, 300: 1250, 400: 1625, 500: 2000, 750: 2750, 1000: 3750},
}

CA_CONFIG = RATES_CONFIG.get("CA") or {
    "currency": "C$",
    "currency_code": "CAD",
    "fuel_price": 1.70,
    "fuel_price_display": "C$1.70/L screening placeholder",
    "bess_rates": {"Ampd 200": 3100, "Ampd 400": 4050},
    "gen_rates": {100: 845, 200: 1180, 300: 1690, 400: 2195, 500: 2700, 750: 3715, 1000: 5065},
    "electricity_rate": 0.19,
    "electricity_rate_display": "C$0.19/kWh screening placeholder",
}

REGION_CONFIGS = {
    "UK": UK_CONFIG,
    "US": US_CONFIG,
    "CA": CA_CONFIG,
}

CANADA_TERMS = (
    "canada", "canadian", "ontario", "quebec", "british columbia", "alberta",
    "saskatchewan", "manitoba", "nova scotia", "new brunswick",
    "newfoundland", "labrador", "prince edward island", "yukon",
    "northwest territories", "nunavut", "toronto", "vancouver", "montreal",
    "montréal", "calgary", "ottawa", "edmonton", "winnipeg", "halifax",
    "hamilton", "mississauga", "brampton", "surrey", "burnaby", "victoria",
    "kitchener", "waterloo", "london ontario", "guelph", "kelowna",
    "markham", "windsor", "regina", "saskatoon",
)


def get_region_config(from_number: str) -> dict:
    """Return regional config based on WhatsApp sender number."""
    # Normalise — strip spaces, dashes
    num = re.sub(r'[\s\-()]', '', from_number or '')
    if num.startswith('+1') or (num.startswith('1') and len(num) == 11):
        return US_CONFIG
    return UK_CONFIG  # default UK


def detect_region_config_from_text(text: str):
    """Return a regional config when the message itself names a region."""
    body = (text or "").lower()
    if any(term in body for term in CANADA_TERMS):
        return CA_CONFIG
    if re.search(r'\b(?:usa|u\.s\.|united states|america|american)\b', body, re.I):
        return US_CONFIG
    if re.search(r'\b(?:uk|u\.k\.|united kingdom|britain|british|england|scotland|wales)\b', body, re.I):
        return UK_CONFIG
    return None


def nearest_gen_rate(gen_kva: float, gen_rates: dict) -> float:
    """Find hire rate for nearest generator kVA size."""
    if not gen_rates:
        return 0
    sizes = sorted(gen_rates.keys())
    # Find smallest size >= gen_kva, otherwise take largest
    for size in sizes:
        if size >= gen_kva:
            return gen_rates[size]
    return gen_rates[sizes[-1]]


LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
}


def _detect_language(text, current_language="en"):
    """Lightweight customer-language detection. Defaults to English when uncertain."""
    body = (text or "").strip()
    override = re.match(r'^\s*(?:LANG|IDIOMA)\s+([A-Z]{2})\b', body, re.I)
    if override:
        code = override.group(1).lower()
        return "es" if code in ("es", "sp") else "en"

    lowered = body.lower()
    spanish_markers = [
        "grúa", "grua", "grúas", "gruas", "semanas", "meses", "red eléctrica", "red electrica",
        "generador", "generadores", "durante", "recarga", "carga desde", "obra", "coste", "ahorro",
        "eléctrica", "electrica", "batería", "bateria",
    ]
    score = sum(1 for marker in spanish_markers if marker in lowered)
    if score >= 1:
        return "es"
    return current_language or "en"


def _strip_language_command(text):
    return re.sub(r'^\s*(?:LANG|IDIOMA)\s+[A-Z]{2}\s*[:\-]?\s*', '', text or '', flags=re.I).strip()


def _normalise_language_input(text, language="en"):
    """Translate supported non-English site-power terms into parser keywords only."""
    if language != "es":
        return text
    normalised = text or ""
    replacements = [
        (r'\bgr[uú]as?\s+torre\b', 'tower cranes'),
        (r'\btorres?\s+gr[uú]a\b', 'tower cranes'),
        (r'\bgr[uú]as?\b', 'cranes'),
        (r'\bpolipastos?\b', 'hoists'),
        (r'\bcabinas?\b', 'cabins'),
        (r'\bsemanas?\b', 'weeks'),
        (r'\bmeses?\b', 'months'),
        (r'\bred\s+el[eé]ctrica\b', 'mains'),
        (r'\bdesde\s+la\s+red\b', 'mains'),
        (r'\bde\s+la\s+red\b', 'mains'),
        (r'\bred\b', 'mains'),
        (r'\bgeneradores?\b', 'generator'),
        (r'\bcomparar\b', 'compare'),
        (r'\bcompara\b', 'compare'),
        (r'\brecarga\b', 'recharge'),
        (r'\bcarga\s+desde\b', ''),
        (r'\bdurante\b', ''),
        (r'\buno\b', 'one'),
        (r'\bdos\b', 'two'),
        (r'\btres\b', 'three'),
        (r'\bcuatro\b', 'four'),
        (r'\bcinco\b', 'five'),
        (r'\bseis\b', 'six'),
        (r'\bsiete\b', 'seven'),
        (r'\bocho\b', 'eight'),
        (r'\bnueve\b', 'nine'),
        (r'\bpequeñ[ao]s?\b', 'small'),
        (r'\bmedias?\b', 'medium'),
        (r'\bgrandes?\b', 'large'),
        (r'\bdiez\b', 'ten'),
    ]
    for pattern, replacement in replacements:
        normalised = re.sub(pattern, replacement, normalised, flags=re.I)
    return re.sub(r'\s+', ' ', normalised).strip()


# Map keyword patterns → exact Loadout EQUIPMENT_SPECS names
EQUIPMENT_KEYWORDS = [
    (["tower crane (large)", "large tower crane", "large tc", "big crane", "luffing", "luffing jib"], "Tower Crane (Large)"),
    (["tower crane (small)", "small tower crane", "small tc", "mini crane", "mini tc"],               "Tower Crane (Small)"),
    (["tower crane", "tower cranes", "crane", "cranes", "tc", "t/c", "tower-crane"],                  "Tower Crane (Medium)"),
    (["passenger hoist", "hoist", "ph", "p/h", "goods hoist", "personnel hoist"],                    "Passenger Hoist"),
    (["mast climber", "mcwp", "mast", "mc", "m/c", "facade hoist"],                                  "Mast Climber"),
    (["welfare", "cabin", "office unit", "site office", "canteen", "drying room"],                    "Site Cabins (Small)"),
    (["welder", "welding", "weld"],                                                                    "Welding Set (6-pack)"),
    (["silo", "mixer", "concrete"],                                                                    "Silo Mixer"),
    (["ev charger", "ev car charger", " ev", "electric charger", "car charger"],                      "EV Car Charger (7kW)"),
]


def match_equipment(text):
    text_lower = text.lower()
    for keywords, name in EQUIPMENT_KEYWORDS:
        for kw in keywords:
            if kw in text_lower:
                return name
    return None


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _qty_token_to_int(token):
    token = (token or "").strip().lower()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def extract_crane_qty(text):
    """Return an explicit crane quantity from phrases like '5x cranes', 'x2 tower cranes', or 'five cranes'."""
    text_lower = (text or "").lower()
    qty_token = r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)'
    patterns = [
        rf'\b{qty_token}\s*[x×]?\s*(?:[a-z]+\s+)?(?:tower\s+)?cranes?\b',
        rf'\b[x×]\s*{qty_token}\s*(?:[a-z]+\s+)?(?:tower\s+)?cranes?\b',
        rf'\b{qty_token}\s*[x×]?\s*(?:wolffkran|wolff|liebherr|potain|falcon|select(?:\s+plant)?)\s+(?:tower\s+)?cranes?\b',
        rf'\b[x×]\s*{qty_token}\s*(?:wolffkran|wolff|liebherr|potain|falcon|select(?:\s+plant)?)\s+(?:tower\s+)?cranes?\b',
        rf'\b[x×]\s*{qty_token}\b(?=[^\n,.]{{0,80}}\b(?:tower\s+)?cranes?\b)',
        rf'\b{qty_token}\s*[x×]\b(?=[^\n,.]{{0,80}}\b(?:tower\s+)?cranes?\b)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text_lower, re.I)
        if m:
            qty_token_value = next((g for g in m.groups() if g), None)
            qty = _qty_token_to_int(qty_token_value)
            if qty and 1 <= qty <= 10:
                return qty
    return None


DEPLOY_MANUFACTURERS_API = "https://deploy.getjoule.co.uk/api/manufacturers"
MANUFACTURER_BRAND_KEYS = {
    "wolffkran": "wolffkran",
    "wolff":     "wolffkran",
    "liebherr":  "liebherr",
    "potain":    "potain",
    "falcon":    "falcon",
    "comansa":   "comansa",
    "select plant": "select_plant",
    "select":    "select_plant",
}
_manufacturer_cache = {}

def _get_manufacturer_data(brand_key):
    """Fetch manufacturer data from Deploy, with the bundled reference as fallback."""
    global _manufacturer_cache
    if brand_key in _manufacturer_cache:
        return _manufacturer_cache[brand_key]
    try:
        resp = requests.get(DEPLOY_MANUFACTURERS_API, timeout=5)
        resp.raise_for_status()
        all_data = resp.json()
        # Cache all brands at once
        for k, v in all_data.items():
            cranes = v.get("saddle_cranes", []) + v.get("luffing_cranes", [])
            _manufacturer_cache[k] = cranes
        if _manufacturer_cache.get(brand_key):
            return _manufacturer_cache[brand_key]
        raise LookupError(f"Deploy returned no data for {brand_key}")
    except Exception as e:
        print(f"[manufacturer API] Error: {e}")
        local_path = os.path.join(_LOCAL_MANUFACTURER_DIR, f"{brand_key}.json")
        try:
            with open(local_path) as handle:
                data = json.load(handle)
            cranes = data.get("saddle_cranes", []) + data.get("luffing_cranes", [])
            _manufacturer_cache[brand_key] = cranes
            return cranes
        except (OSError, ValueError) as local_error:
            print(f"[manufacturer data] Local fallback unavailable: {local_error}")
            return []

def _lookup_manufacturer_crane_row(text):
    """Check if message mentions a crane manufacturer/model. Returns the matched manufacturer row."""
    text_lower = text.lower()

    matched_key = None
    matched_brand = None
    for brand, key in MANUFACTURER_BRAND_KEYS.items():
        if brand in text_lower:
            matched_key = key
            matched_brand = brand
            break

    if not matched_key:
        return None

    try:
        cranes = _get_manufacturer_data(matched_key)
        if not cranes:
            return None

        normalized_text = re.sub(r'[^A-Z0-9]+', '', text.upper())
        for crane in cranes:
            crane_model = crane.get("model", "").upper()
            crane_model_clean = crane_model.replace(" ", "").replace("-", "")
            if crane_model_clean and crane_model_clean in normalized_text:
                return crane

        # Try to match a model number from the text
        # Extract numbers+letters that look like model IDs (e.g. 630B, 81K, MDT178, EC-B200)
        model_tokens = re.findall(r'\b([A-Z]?[A-Z]?\d+[A-Z\-]*\d*[A-Z]?)\b', text.upper())
        # Prefer explicit model-like tokens (WK166B) before bare quantities (2).
        model_tokens = sorted(set(model_tokens), key=lambda token: (len(token), any(ch.isalpha() for ch in token)), reverse=True)

        best_crane = None
        for token in model_tokens:
            for crane in cranes:
                crane_model = crane.get("model", "").upper().replace(" ", "").replace("-", "")
                token_clean = token.replace("-", "")
                if token_clean in crane_model or crane_model in token_clean:
                    best_crane = crane
                    break
            if best_crane:
                break

        if best_crane:
            return best_crane

        # Brand-only or non-exact model mentions are not enough for proposal-grade sizing.
        # Force the caller to ask for an exact model/spec sheet instead of sizing from an average.
        return None

    except Exception as e:
        print(f"[manufacturer lookup] Error: {e}")
        return None


def lookup_manufacturer_crane(text):
    """Check if message mentions a crane manufacturer/model. Returns (peak_kw, model_name) or (None, None)."""
    row = _lookup_manufacturer_crane_row(text)
    if not row:
        return None, None
    return row.get("peak_kw", 0), row.get("model")


def _brand_and_cranes_for_text(text):
    text_lower = text.lower()
    for brand, key in MANUFACTURER_BRAND_KEYS.items():
        if brand in text_lower:
            return brand, key, _get_manufacturer_data(key)
    return None, None, []


def _clean_model_token(value):
    return (value or "").upper().replace(" ", "").replace("-", "")


def _nearest_manufacturer_model(token, cranes):
    """Find a same-family nearby model when the exact token is not in the database."""
    token_clean = _clean_model_token(token)
    match = re.match(r'^([A-Z]+)(\d+)([A-Z]*)$', token_clean)
    if not match:
        return None
    prefix, number, suffix = match.groups()
    token_num = int(number)
    candidates = []
    for crane in cranes:
        model_clean = _clean_model_token(crane.get("model"))
        model_match = re.match(r'^([A-Z]+)(\d+)([A-Z]*)$', model_clean)
        if not model_match:
            continue
        model_prefix, model_number, model_suffix = model_match.groups()
        if model_prefix != prefix or model_suffix != suffix:
            continue
        diff = abs(int(model_number) - token_num)
        # Same family and close number: useful alternative, not a random substitution.
        if diff <= max(5, token_num * 0.01):
            candidates.append((diff, model_clean, crane))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _manufacturer_model_substitutions(text):
    """Return explicit model tokens that need exact or nearest-neighbour handling."""
    text_upper = text.upper()
    _, _, cranes = _brand_and_cranes_for_text(text)
    if not cranes:
        return []
    known_models = {
        _clean_model_token(crane.get("model"))
        for crane in cranes
        if crane.get("model")
    }
    substitutions = []
    tokens = re.findall(r'\b([A-Z]{1,4}\d{2,5}[A-Z]?(?:-\d+)?)\b', text_upper)
    for token in sorted(set(tokens)):
        token_clean = _clean_model_token(token)
        if not token_clean or token_clean in known_models:
            continue
        nearest = _nearest_manufacturer_model(token, cranes)
        substitutions.append({"input": token_clean, "nearest": nearest})
    return substitutions


def _model_qty(text, token):
    pattern = rf'\b(?:([0-9]+)\s*[x×]\s*)?(?:[A-Za-z]+\s+)?{re.escape(token)}\b'
    match = re.search(pattern, text, re.I)
    if match and match.group(1):
        return int(match.group(1))
    return 1


def parse_message(text):
    """Parse natural language load list into Loadout-compatible items + weeks."""
    text = text.strip()

    # Recharge source — default generator, override if mains/grid mentioned
    recharge_source = "gen"
    if re.search(r'\b(mains|grid|mains power|grid power)\b', text, re.I):
        recharge_source = "mains"

    # Duration — weeks or months
    weeks = 12  # default
    duration_explicit = False
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:weeks?|wks?|w\b)', text, re.I)
    if m:
        weeks = float(m.group(1))
        duration_explicit = True
    else:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:months?|mths?|mnths?|mos?)', text, re.I)
        if m:
            weeks = float(m.group(1)) * 4.33
            duration_explicit = True

    # Check full message for manufacturer crane reference
    full_mfr_row = _lookup_manufacturer_crane_row(text)
    full_mfr_peak_kw = full_mfr_row.get("peak_kw", 0) if full_mfr_row else None
    full_mfr_model = full_mfr_row.get("model") if full_mfr_row else None
    model_substitutions = _manufacturer_model_substitutions(text)
    mfr_qty = extract_crane_qty(text) or 1
    mfr_crane_added = False

    # Split on commas, semicolons, newlines, and simple "and" load lists.
    # This lets messages like "1 hoist and 2 welfare cabins" create two items.
    parts = re.split(r'[,;\n]+|\s+and\s+', text, flags=re.I)

    items = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(r'^\d+\s*(weeks?|months?)$', part, re.I):
            continue

        qty = 1
        m = re.match(r'^(?:[x×]\s*)?(\d+)\s*[x×]\s*(.+)', part, re.I)
        if m:
            qty = int(m.group(1))
            part = m.group(2).strip()
        else:
            m = re.match(r'^[x×]\s*(\d+)\s+(.+)', part, re.I)
            if m:
                qty = int(m.group(1))
                part = m.group(2).strip()
            else:
                m = re.match(r'^(\d+)\s+(.+)', part, re.I)
                if m:
                    qty = int(m.group(1))
                    part = m.group(2).strip()

        kva = 0
        m = re.search(r'(\d+(?:\.\d+)?)\s*kva', part, re.I)
        if m:
            kva = float(m.group(1))
        else:
            m = re.search(r'(\d+(?:\.\d+)?)\s*kw\b', part, re.I)
            if m:
                kva = float(m.group(1)) / 0.8

        name = match_equipment(part)
        if name:
            if qty == 1 and "crane" in name.lower() and mfr_qty:
                qty = mfr_qty
            # If no kVA given, try manufacturer lookup for accurate crane specs
            item_model = None
            item_gen_size_kva = None
            if kva == 0 and "crane" in name.lower():
                mfr_row = _lookup_manufacturer_crane_row(part) or full_mfr_row
                mfr_peak_kw = mfr_row.get("peak_kw", 0) if mfr_row else None
                mfr_model = mfr_row.get("model") if mfr_row else None
                if mfr_peak_kw:
                    # Convert peak_kw back to kva equivalent for Loadout (peak_kw = kva * 0.66)
                    kva = round(mfr_peak_kw / 0.66, 1)
                    item_model = mfr_model
                    item_gen_size_kva = mfr_row.get("gen_size_kva") or mfr_row.get("min_gen_kva_raw")
                    print(f"[Surge] Manufacturer lookup: {mfr_model} → peak_kw={mfr_peak_kw}, kva={kva}")
                elif re.search(r'\b(?:feed|feeding|power|powered|powering|output|recharge|charging|mains|grid|generator|gen|distribution|db|panel)\b', part, re.I):
                    continue
            item = {"name": name, "qty": qty, "kva": kva, "weeks": weeks}
            if item_model:
                item["_model"] = item_model
                item["_label"] = f"Tower Crane ({item_model})"
            if item_gen_size_kva:
                item["_gen_size_kva"] = item_gen_size_kva
            items.append(item)
            if "crane" in name.lower():
                mfr_crane_added = True

    for substitution in model_substitutions:
        nearest = substitution.get("nearest")
        if not nearest:
            continue
        input_model = substitution["input"]
        if any(item.get("_source_model_input") == input_model for item in items):
            continue
        nearest_model = nearest.get("model")
        peak_kw = float(nearest.get("peak_kw") or 0)
        if not nearest_model or peak_kw <= 0:
            continue
        kva_equiv = round(peak_kw / 0.66, 1)
        qty = _model_qty(text, input_model)
        item = {
            "name": "Tower Crane (Medium)",
            "qty": qty,
            "kva": kva_equiv,
            "weeks": weeks,
            "_model": nearest_model,
            "_source_model_input": input_model,
            "_label": f"Tower Crane ({input_model} screened as {nearest_model})",
        }
        gen_size = nearest.get("gen_size_kva") or nearest.get("min_gen_kva_raw")
        if gen_size:
            item["_gen_size_kva"] = gen_size
        items.append(item)

    if any(substitution.get("nearest") for substitution in model_substitutions):
        items = [
            item for item in items
            if not (
                (item.get("name") or "").startswith("Tower Crane")
                and not item.get("_model")
                and not float(item.get("kva") or 0)
            )
        ]

    # If user replied with a standalone load figure, apply it to a single unresolved item
    unresolved_items = [item for item in items if not item.get("kva")]
    text_kva = re.findall(r'(\d+(?:\.\d+)?)\s*kva', text, re.I)
    text_kw = re.findall(r'(\d+(?:\.\d+)?)\s*kw\b', text, re.I)
    text_qty = re.findall(r'\b(\d+)\s*[x×]\b', text, re.I)
    if len(unresolved_items) == 1 and unresolved_items[0]["name"].startswith("Tower Crane"):
        if len(text_qty) == 1 and unresolved_items[0].get("qty", 1) == 1:
            unresolved_items[0]["qty"] = int(text_qty[0])
        if len(text_kva) == 1:
            unresolved_items[0]["kva"] = float(text_kva[0])
        elif len(text_kw) == 1:
            unresolved_items[0]["kva"] = float(text_kw[0]) / 0.8

    # If manufacturer was detected but no tower crane was added from keywords, add it
    if full_mfr_peak_kw and not mfr_crane_added:
        kva_equiv = round(full_mfr_peak_kw / 0.66, 1)
        crane_label = f"Tower Crane ({full_mfr_model})" if full_mfr_model else "Tower Crane (Medium)"
        item = {"name": "Tower Crane (Medium)", "qty": mfr_qty, "kva": kva_equiv, "weeks": weeks, "_model": full_mfr_model, "_label": crane_label}
        full_gen_size = full_mfr_row.get("gen_size_kva") or full_mfr_row.get("min_gen_kva_raw")
        if full_gen_size:
            item["_gen_size_kva"] = full_gen_size
        items.append(item)
        print(f"[Surge] Auto-added crane from manufacturer lookup: {full_mfr_model} → {kva_equiv}kVA")

    return (items if items else None), weeks, recharge_source, {
        "duration_explicit": duration_explicit,
        "recharge_explicit": bool(re.search(r'\b(gen|generator|mains|grid)\b', text, re.I)),
        "manufacturer_matched": bool(full_mfr_peak_kw),
        "unmatched_manufacturer_models": [s["input"] for s in model_substitutions if not s.get("nearest")],
        "model_substitutions": [
            {"input": s["input"], "nearest": (s.get("nearest") or {}).get("model")}
            for s in model_substitutions
        ],
        "power_path_explicit": bool(re.search(
            r'\b(?:ampd|battery|bess|generator|gen|mains|grid|distribution|db|panel|supply|feed|feeding|powering|powered)\b',
            text,
            re.I,
        )),
    }


def call_loadout(items, weeks, recharge_source="gen", region=None):
    """Call Loadout /api/calculate — single source of truth for all rates & specs."""
    cfg = region or UK_CONFIG
    payload = {
        "weeks": weeks,
        "hours": 50,
        "fuel_price": cfg["fuel_price"],
        "electricity_rate": cfg.get("electricity_rate", cfg.get("mains_price", 0.25)),
        "recharge_source": recharge_source,
        "items": [],
    }
    for item in items:
        payload_kva = item.get("_gen_size_kva") or item["kva"]
        if item.get("_gen_size_kva"):
            payload_kva = _generator_rate_for_size(float(item["_gen_size_kva"]), cfg)[0] or payload_kva
        payload_item = {
            "name": item["name"],
            "qty": item["qty"],
            "weeks": weeks,
            "kva": payload_kva,
        }
        if item.get("_model") and item.get("kva"):
            derived_peak_kw = float(item["kva"]) * 0.66
            payload_item["peak_kw"] = round(derived_peak_kw, 1)
            payload_item["utilisation"] = 10
        payload["items"].append(payload_item)
    resp = requests.post(LOADOUT_API, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_comment(items, weeks, savings, co2_saved, currency="£"):
    names = [i["name"] for i in items]
    total_qty = sum(i["qty"] for i in items)
    total_kva = sum(i["qty"] * (i["kva"] or 80) for i in items)

    has_tc = any("Tower Crane" in n for n in names)
    has_hoist = any("Hoist" in n for n in names)
    has_mast = any("Mast Climber" in n for n in names)

    if has_tc and has_hoist and has_mast:
        opener = "Tower crane, hoist, and mast climbers — that's a big structural package. 🏗️"
    elif has_tc and weeks >= 52:
        opener = "A tower crane for a full year — this is a proper project. 🏗️"
    elif has_tc:
        opener = "Tower crane on site — something's going up. 🏗️"
    elif has_mast and has_hoist:
        opener = "Mast climbers and a hoist — lots of vertical movement on this one. ⬆️"
    elif has_mast:
        opener = "Mast climbers — facade works? Either way, that's a tidy little load. 🧱"
    elif total_qty >= 4:
        opener = f"Busy site — {total_qty} pieces of kit. Love to see it. ⚡"
    elif total_kva >= 500:
        opener = f"That's a {total_kva:.0f}kVA load — nothing shy about this site. 💪"
    elif weeks >= 52:
        opener = "A year-long project — the longer it runs, the better BESS looks. 📈"
    else:
        opener = "Right, let's crunch the numbers. ⚡"

    if savings >= 100000:
        saving_quip = f"Saving {currency}{savings:,.0f} — that's not a rounding error, that's a result. 💰"
    elif savings >= 50000:
        saving_quip = f"{currency}{savings:,.0f} back in the budget. Your finance team will be pleased. 💰"
    elif savings >= 20000:
        saving_quip = f"{currency}{savings:,.0f} saved — worth the conversation, isn't it? 💰"
    elif savings > 0:
        saving_quip = f"{currency}{savings:,.0f} saved vs diesel. Every bit counts. 💰"
    else:
        saving_quip = "Short hire — generator wins this time, but check a longer duration. 📊"

    cars = int(co2_saved * 1000 / 4600)
    if co2_saved >= 100:
        co2_quip = f"Oh, and {co2_saved:.0f} tonnes of CO₂ avoided — that's {cars} cars off the road for a year. 🌱"
    elif co2_saved >= 20:
        co2_quip = f"{co2_saved:.1f} tonnes of CO₂ avoided. Scope 3 reporting just got easier. 🌱"
    else:
        co2_quip = ""

    return opener, saving_quip, co2_quip


def apply_regional_overrides(data, region_cfg, weeks):
    """Apply non-UK regional hire rate overrides to a Loadout response dict."""
    if region_cfg.get("currency_code") == "GBP":
        return data
    cur = region_cfg["currency"]
    bess_name = (
        (data.get("recommended_bess") or {}).get("name") if isinstance(data.get("recommended_bess"), dict)
        else data.get("recommended_bess")
    ) or (data.get("ampd") or {}).get("unit_name") or "Ampd 200"
    bess_name = str(bess_name)
    bess_weekly = region_cfg["bess_rates"].get("Ampd 400" if "400" in bess_name else "Ampd 200", 2000)
    gen_kva = data.get("gen_kva") or data.get("generator", {}).get("kva", 200)
    if isinstance(gen_kva, dict):
        gen_kva = gen_kva.get("kva", 200)
    gen_weekly_rate = nearest_gen_rate(float(gen_kva or 200), region_cfg["gen_rates"])
    project_weeks = data.get("weeks", weeks)
    # Generator total: regional hire rate + fuel cost (Loadout already calculated at regional fuel unit price)
    fuel_liters = data.get("baseline", {}).get("fuel_liters", 0)
    fuel_cost   = fuel_liters * region_cfg.get("fuel_price", 1.321)
    data["_us_gen_total"]    = gen_weekly_rate * project_weeks + fuel_cost
    data["_us_gen_weekly"]   = gen_weekly_rate  # hire-only; fuel included in total

    # BESS total: regional hire rate + recharge overhead (gen hire+fuel or mains electricity)
    # Strip out the UK hire cost from ampd.cost_total to isolate the recharge overhead,
    # then add the US hire rate back in. Recharge fuel is already in USD (correct $/L passed).
    ampd_data       = data.get("ampd", {})
    uk_hire_weekly  = ampd_data.get("weekly_rate", 0)
    hire_weeks      = ampd_data.get("hire_weeks", project_weeks)
    uk_hire_total   = uk_hire_weekly * hire_weeks
    recharge_overhead = ampd_data.get("cost_total", 0) - uk_hire_total
    data["_us_bess_total"]   = bess_weekly * project_weeks + recharge_overhead
    data["_us_bess_weekly"]  = bess_weekly
    data["_us_currency"]     = cur
    data["_us_fuel_display"] = region_cfg["fuel_price_display"]
    return data


def apply_us_overrides(data, region_cfg, weeks):
    """Backward-compatible wrapper for older callers/tests."""
    return apply_regional_overrides(data, region_cfg, weeks)

def _recommended_unit_name(data):
    recommended = data.get("recommended_bess") or {}
    if isinstance(recommended, dict):
        return recommended.get("name") or recommended.get("unit_name")
    if recommended:
        return str(recommended)
    return (data.get("ampd") or {}).get("unit_name") or "Ampd BESS"


def _serialize_items(items):
    return [
        {
            "name": i["name"],
            "qty": i.get("qty", 1),
            "kva": i.get("kva", 0),
            "weeks": i.get("weeks"),
            "_model": i.get("_model"),
            "_source_model_input": i.get("_source_model_input"),
        }
        for i in (items or [])
    ]


def _clone_items(items):
    return [dict(i) for i in (items or [])]


def _scenario_state(items, weeks, recharge_source, region_cfg, job_id=None):
    return {
        "items": _serialize_items(items),
        "weeks": weeks,
        "recharge_source": recharge_source,
        "region_cfg": region_cfg,
        "job_id": job_id,
    }


def _equipment_name_from_text(text):
    matched = match_equipment(text or "")
    if matched:
        return matched
    lowered = (text or "").lower()
    if "crane" in lowered:
        return "Tower Crane (Medium)"
    return None


def _merge_item(existing_items, new_item):
    for item in existing_items:
        if item["name"] == new_item["name"] and float(item.get("kva") or 0) == float(new_item.get("kva") or 0):
            item["qty"] = item.get("qty", 1) + new_item.get("qty", 1)
            return
    existing_items.append(dict(new_item))


def _apply_followup(body, scenario):
    if not scenario:
        return None

    text = body.strip()
    lower = text.lower()
    items = _clone_items(scenario.get("items", []))
    weeks = scenario.get("weeks", 12)
    recharge_source = scenario.get("recharge_source", "gen")
    compare_mode = False
    changed = False

    week_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:weeks?|wks?|w\b)', lower)
    month_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:months?|mths?|mnths?|mos?)', lower)
    if week_match:
        weeks = float(week_match.group(1))
        changed = True
    elif month_match:
        weeks = float(month_match.group(1)) * 4.33
        changed = True
    elif re.fullmatch(r'\d+(?:\.\d+)?', lower):
        weeks = float(lower)
        changed = True

    if re.search(r'\b(compare|vs|versus)\b', lower):
        compare_mode = True
        changed = True
    if re.search(r'\b(mains|grid)\b', lower):
        recharge_source = "mains"
        changed = True
    elif re.search(r'\b(generator|gen)\b', lower):
        recharge_source = "gen"
        changed = True

    qty_match = re.search(r'\b(?:make it|change to|use|set to)?\s*(\d+)\s*(?:x\s*)?(tower cranes?|tower crane|cranes?|passenger hoists?|passenger hoist|hoists?|mast climbers?|mast climber|climbers?|welfare cabins?|welfare cabin|cabins?|site cabins?|site cabin|site offices?|site office)\b', lower)
    if qty_match:
        qty = int(qty_match.group(1))
        equip_name = _equipment_name_from_text(qty_match.group(2))
        if equip_name:
            updated = False
            for item in items:
                if item["name"] == equip_name or (equip_name.startswith("Tower Crane") and item["name"].startswith("Tower Crane")):
                    item["qty"] = qty
                    item["weeks"] = weeks
                    updated = True
                    changed = True
                    break
            if not updated:
                items.append({"name": equip_name, "qty": qty, "kva": 0, "weeks": weeks})
                changed = True

    add_match = re.search(r'\badd(?:ing)?\b(.+)$', text, re.I)
    if add_match:
        added_text = add_match.group(1).strip()
        another_match = re.search(r'\b(?:an?\s+)?another\s+(tower cranes?|tower crane|cranes?|passenger hoists?|passenger hoist|hoists?|mast climbers?|mast climber|climbers?|welfare cabins?|welfare cabin|cabins?|site cabins?|site cabin|site offices?|site office)\b', added_text.lower())
        if another_match:
            equip_name = _equipment_name_from_text(another_match.group(1))
            if equip_name:
                updated = False
                for item in items:
                    if item["name"] == equip_name or (equip_name.startswith("Tower Crane") and item["name"].startswith("Tower Crane")):
                        item["qty"] = item.get("qty", 1) + 1
                        item["weeks"] = weeks
                        updated = True
                        changed = True
                        break
                if not updated:
                    items.append({"name": equip_name, "qty": 1, "kva": 0, "weeks": weeks})
                    changed = True
        else:
            added_items, _, _, _ = parse_message(added_text)
            for item in added_items or []:
                item["weeks"] = weeks
                _merge_item(items, item)
                changed = True

    for item in items:
        item["weeks"] = weeks

    if not changed:
        return None
    return {"items": items, "weeks": weeks, "recharge_source": recharge_source, "compare_mode": compare_mode}


def _generator_size_label(data):
    gen_kva = data.get("gen_kva") or (data.get("generator") or {}).get("kva") or (data.get("baseline") or {}).get("gen_kva")
    if isinstance(gen_kva, dict):
        gen_kva = gen_kva.get("kva")
    try:
        return f"{float(gen_kva):.0f}kVA"
    except (TypeError, ValueError):
        return None


def _loadout_knowledge():
    try:
        with open(_LOADOUT_KNOWLEDGE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _load_field_evidence_cases():
    for path in _FIELD_EVIDENCE_FILES:
        try:
            with open(path) as f:
                payload = json.load(f)
            return payload.get("cases", []) if isinstance(payload, dict) else []
        except Exception:
            continue
    return []


def _norm_evidence_text(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').lower())


def _field_evidence_lines(items):
    cases = _load_field_evidence_cases()
    if not cases:
        return []
    lines = []
    seen = set()
    for item in items or []:
        model = item.get("_model") or item.get("_label") or item.get("name")
        model_key = _norm_evidence_text(model)
        if not model_key or model_key == "towercranemedium":
            continue
        qty = int(item.get("qty") or 1)
        matches = []
        for case in cases:
            haystack = _norm_evidence_text(" ".join(
                [str(case.get("result") or ""), str(case.get("ampd_setup") or "")]
                + [str(x) for x in case.get("powered", [])]
                + [str(x) for x in case.get("plant_models", [])]
                + [str(x) for x in case.get("commercial_notes", [])]
            ))
            if model_key not in haystack:
                continue
            case_id = case.get("id") or case.get("site") or model_key
            if case_id in seen:
                continue
            score = 1
            if qty == 2 and (
                f"2x{model_key}" in haystack
                or f"2xwolffkran{model_key}" in haystack
                or f"twowolffkran{model_key}" in haystack
                or f"two{model_key}" in haystack
            ):
                score = 10
            elif qty > 1 and (f"{qty}x{model_key}" in haystack or f"{qty}xwolffkran{model_key}" in haystack):
                score = 10
            matches.append((score, case, case_id, haystack))
        if not matches:
            continue
        _, case, case_id, haystack = sorted(matches, key=lambda row: row[0], reverse=True)[0]
        if case_id in seen:
            continue
        seen.add(case_id)
        result = str(case.get("result") or "").strip()
        result = result.split(". ")[0].strip()
        status = case.get("status") or "field evidence"
        confidence = case.get("confidence") or "unknown confidence"
        if qty == 2 and (
            f"2x{model_key}" in haystack
            or f"2xwolffkran{model_key}" in haystack
            or f"twowolffkran{model_key}" in haystack
            or f"two{model_key}" in haystack
        ):
            scope = "closest match: 2-crane measured setup"
        elif qty > 1:
            scope = "related measured case, not exact quantity proof"
        else:
            scope = "matched measured case"
        result = result.rstrip(".")
        lines.append(
            f"• Field evidence ({status}, {confidence}; {scope}): {result}."
        )
    return lines


def _interpolate_lookup(value, lookup):
    if not lookup:
        return None
    points = sorted((float(k), float(v)) for k, v in lookup.items())
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (lo_k, lo_v), (hi_k, hi_v) in zip(points, points[1:]):
        if lo_k <= value <= hi_k:
            if hi_k == lo_k:
                return lo_v
            ratio = (value - lo_k) / (hi_k - lo_k)
            return lo_v + ((hi_v - lo_v) * ratio)
    return None


def _loadout_screening_lines(items):
    knowledge = _loadout_knowledge()
    peak_lookup = knowledge.get("crane_generator_kva_to_peak_kw") or {}
    utilisation = ((knowledge.get("default_assumptions") or {}).get("crane_utilisation_pct_for_avg") or 10) / 100
    lines = []
    field_lines = _field_evidence_lines(items)
    if field_lines:
        lines.extend(field_lines)
    for item in items or []:
        if item.get("_source_model_input") and item.get("_model"):
            lines.append(
                f"• Model check: user supplied {item['_source_model_input']}; database does not have that exact model, "
                f"so this screen uses nearest manufacturer record {item['_model']}. Confirm only if that substitution materially changes the answer."
            )
    for item in items or []:
        if not (item.get("name") or "").startswith("Tower Crane"):
            continue
        kva = float(item.get("kva") or 0)
        if kva <= 0:
            continue
        if item.get("_model"):
            peak_kw = kva * 0.66
        else:
            peak_kw = _interpolate_lookup(kva, peak_lookup)
        if peak_kw is None:
            continue
        avg_kw = peak_kw * utilisation
        qty = int(item.get("qty") or 1)
        qty_text = f"{qty} x " if qty > 1 else ""
        total_peak = peak_kw * qty
        total_avg = avg_kw * qty
        allowance_label = "derived allowance" if item.get("_model") else "generator allowance"
        lines.append(
            f"• Based on the {qty_text}{kva:.0f}kVA {allowance_label}, I'd screen this at roughly "
            f"{total_peak:.0f}kW peak and {total_avg:.1f}kW average demand. That is a sizing assumption, not a measured load profile."
        )
    if lines:
        lines.append("• To tighten it up, I'd want the actual load profile or at least crane model, operating hours and charge source.")
    return lines


def _split_field_evidence_first(screening_lines):
    evidence = []
    rest = []
    for line in screening_lines or []:
        if line.startswith("• Field evidence"):
            evidence.append(line)
        else:
            rest.append(line)
    return evidence, rest


def _field_evidence_reason(items, unit_name):
    if "200" not in (unit_name or "").lower():
        return None
    field_lines = _field_evidence_lines(items)
    for line in field_lines:
        if "closest match" in line and "telemetry_backed" in line:
            return (
                "Recommended against measured field evidence from a matching setup; "
                "final connection design still needs normal site electrical checks."
            )
    if field_lines:
        return (
            "Recommended with supporting field evidence; final connection design still needs normal site electrical checks."
        )
    return None


def _grid_upgrade_screen(text, region_cfg):
    """Return a UK grid-upgrade rule-of-thumb line when existing/needed kW is stated."""
    if (region_cfg or {}).get("currency_code") != "GBP":
        return None
    body = text or ""
    existing_patterns = [
        r'\b(?:have|has|got|available|existing|current(?:ly)?(?:\s+have)?)\s+(?:only\s+)?(\d+(?:\.\d+)?)\s*kw\b',
        r'\b(\d+(?:\.\d+)?)\s*kw\s+(?:available|existing|current|on[ -]?site|supply)\b',
    ]
    target_patterns = [
        r'\b(?:need|needs|required|require|requires|target)\s+(\d+(?:\.\d+)?)\s*kw\b',
        r'\b(?:need|needs|required|require|requires|target)\s+(?:around|about|roughly|approx(?:imately)?)?\s*(\d+(?:\.\d+)?)\s*kw\b',
    ]

    def first_number(patterns):
        for pattern in patterns:
            match = re.search(pattern, body, re.I)
            if match:
                try:
                    return float(match.group(1))
                except (TypeError, ValueError):
                    return None
        return None

    existing_kw = first_number(existing_patterns)
    target_kw = first_number(target_patterns)
    if existing_kw is None or target_kw is None or target_kw <= existing_kw:
        return None

    upgrade_kw = target_kw - existing_kw
    cost_per_kw = float((region_cfg or {}).get("grid_upgrade_cost_per_kw", 1000))
    upgrade_cost = upgrade_kw * cost_per_kw
    return (
        f"• UK grid upgrade screen: existing {existing_kw:.0f}kW → required {target_kw:.0f}kW "
        f"= {upgrade_kw:.0f}kW upgrade, rule-of-thumb ~£{upgrade_cost:,.0f}."
    )



def _assumption_lines(data, weeks, recharge_source, fuel_display):
    lines = [f"• Duration: {int(round(weeks))} weeks"]
    lines.append(f"• Recharge: {'mains charge' if recharge_source == 'mains' else 'generator recharge'}")
    lines.append(f"• Fuel price: {fuel_display}")
    gen_size = _generator_size_label(data)
    if gen_size:
        lines.append(f"• Generator assumed: {gen_size}")
    ampd = data.get("ampd") or {}
    charge_kw = ampd.get("recharge_charge_kw")
    standby_kw = ampd.get("recharge_standby_kw")
    min_gen_kva = ampd.get("recharge_min_generator_kva")
    if charge_kw:
        lines.append(f"• AMPD charge rate modelled: {float(charge_kw):.0f}kW max")
    if standby_kw:
        lines.append(f"• AMPD self-consumption while on: {float(standby_kw):g}kWh/hour")
    if min_gen_kva and recharge_source == "gen":
        lines.append(f"• Charge generator electrical minimum: {float(min_gen_kva):.1f}kVA at 0.8PF before rounding to hire size")
    if ampd.get("recharge_efficiency"):
        lines.append("• Conversion efficiency: 90% usable output per kWh charged")
    return lines


def _charging_assumption_lines(data, recharge_source):
    ampd = data.get("ampd") or {}
    charge_kw = ampd.get("recharge_charge_kw")
    standby_kw = ampd.get("recharge_standby_kw")
    min_gen_kva = ampd.get("recharge_min_generator_kva")
    lines = []
    if charge_kw:
        lines.append(f"• Charge rate: {float(charge_kw):.0f}kW max")
    if standby_kw:
        lines.append(f"• Unit self-consumption: {float(standby_kw):g}kWh/hour while on")
    if min_gen_kva and recharge_source == "gen":
        lines.append(f"• Generator sizing: {float(min_gen_kva):.1f}kVA minimum at 0.8PF, rounded up to available hire size")
    if ampd.get("recharge_efficiency"):
        lines.append("• Conversion: 90% usable output from charged energy")
    return lines



def _unit_reason(unit_name, region_code="GBP"):
    unit = (unit_name or "").lower()
    if region_code == "USD":
        if "400" in unit:
            return "Higher site demand or longer runtime points to Ampd 400."
        if "200" in unit:
            return "This load profile fits Ampd 200 without oversizing."
        return None
    if "400" in unit:
        return "Higher site demand or longer run time points to Ampd 400."
    if "200" in unit:
        return "This load profile fits Ampd 200 without oversizing the unit."
    return None


def _unit_reason_i18n(unit_name, region_code="GBP", language="en"):
    if language != "es":
        return _unit_reason(unit_name, region_code)
    unit = (unit_name or "").lower()
    if "400" in unit:
        return "La demanda o el tiempo de funcionamiento apunta a Ampd 400."
    if "200" in unit:
        return "Este perfil encaja con Ampd 200 sin sobredimensionar la unidad."
    return None


def _regional_copy(region_code="GBP"):
    if region_code == "CAD":
        return {
            "title": "⚡ *Surge - Power Snapshot*",
            "loads": "📋 *Site load*",
            "generator": "🔴 *Diesel generator*",
            "bess": "🟢 *Ampd BESS*",
            "assumptions": "📝 *Assumptions*",
            "contact": "Reply *TALK* or *CONTACT* and I’ll have the Ampd team pick this up for Canada.",
            "signoff": "Surge by Ampd Energy ⚡",
        }
    if region_code == "USD":
        return {
            "title": "⚡ *Surge - Power Snapshot*",
            "loads": "📋 *Site load*",
            "generator": "🔴 *Diesel generator*",
            "bess": "🟢 *Ampd BESS*",
            "assumptions": "📝 *Assumptions*",
            "contact": "Reply *TALK* or *CONTACT* and I’ll have the Ampd team reach out.",
            "signoff": "Surge by Ampd Energy ⚡",
        }
    return {
        "title": "⚡ *Surge - Power Snapshot*",
        "loads": "📋 *Site load*",
        "generator": "🔴 *Diesel generator*",
        "bess": "🟢 *Ampd BESS*",
        "assumptions": "📝 *Assumptions*",
        "contact": "Reply *TALK* or *CONTACT* and I’ll get the Ampd team to pick this up.",
        "signoff": "Surge by Ampd Energy ⚡",
    }


def _lead_cta(savings, gen_total, region_code="GBP"):
    strong_result = savings >= 20000 or (gen_total > 0 and savings / gen_total >= 0.15)
    if not strong_result:
        return None
    if region_code == "CAD":
        return "Strong result. If you want, I can hand this to the Ampd team for Canada."
    if region_code == "USD":
        return "Strong result. If you want, I can hand this straight to the Ampd team."
    return "Strong result. If you want, I can hand this straight over to the Ampd team."


def _savings_summary_line(cur, savings, co2_saved, weeks):
    if savings >= 0:
        return f"• Saves: *{cur}{savings:,.0f}* and *{co2_saved:.1f}t CO2* over {int(round(weeks))} weeks"
    return f"• Cost delta: *{cur}{abs(savings):,.0f} higher* vs diesel; *{co2_saved:.1f}t CO2* avoided over {int(round(weeks))} weeks"



def _next_step_options(items, weeks, recharge_source, compare_mode=False):
    has_crane = any((item.get("name") or "").startswith("Tower Crane") for item in (items or []))
    has_single_crane = any((item.get("name") or "").startswith("Tower Crane") and int(item.get("qty", 1) or 1) == 1 for item in (items or []))
    next_weeks = 52 if int(round(weeks)) < 52 else 26
    alt_recharge = "compare mains" if recharge_source != "mains" else "compare generator"
    options = [
        f"• Try: *what about {next_weeks} weeks*",
        f"• Try: *{alt_recharge}*",
        "• Try: *add a welfare cabin*",
    ]
    if has_crane and has_single_crane:
        options.append("• Try: *make it 2 cranes*")
    options.append("• Try: *CONTACT*")
    return ["", "*Try next*", *options]


def _next_step_options_i18n(items, weeks, recharge_source, compare_mode=False, language="en"):
    if language != "es":
        return _next_step_options(items, weeks, recharge_source, compare_mode)
    has_crane = any((item.get("name") or "").startswith("Tower Crane") for item in (items or []))
    next_weeks = 52 if int(round(weeks)) < 52 else 26
    alt_recharge = "comparar red" if recharge_source != "mains" else "comparar generador"
    options = [
        f"• Prueba: *qué pasa con {next_weeks} semanas*",
        f"• Prueba: *{alt_recharge}*",
        "• Prueba: *añadir una cabina de obra*",
    ]
    if has_crane:
        options.append("• Prueba: *hacerlo con 2 grúas*")
    options.append("• Prueba: *CONTACTO*")
    return ["", "*Prueba después*", *options]


def _display_item(item):
    """Human-friendly scenario line. Hide internal Loadout bucket labels when explicit load is known."""
    name = item.get("name", "Equipment")
    qty = item.get("qty", 1)
    kva = item.get("kva", 0) or 0
    if name.startswith("Tower Crane"):
        base = item.get("_label") or "Tower Crane"
    else:
        base = name
    qty_str = f" x{qty}" if qty > 1 else ""
    if kva > 0:
        per_unit = " each" if qty > 1 else ""
        if item.get("_model"):
            return f"• {base}{qty_str} — {kva:.0f}kVA derived allowance{per_unit}"
        return f"• {base}{qty_str} — {kva:.0f}kVA{per_unit}"
    return f"• {base}{qty_str}"


def _display_item_i18n(item, language="en"):
    if language != "es":
        return _display_item(item)
    name = item.get("name", "Equipo")
    qty = item.get("qty", 1)
    kva = item.get("kva", 0) or 0
    if name.startswith("Tower Crane"):
        base = "Grúa torre"
    elif name.startswith("Passenger Hoist"):
        base = "Montacargas"
    elif name.startswith("Mast Climber"):
        base = "Plataforma trepadora"
    elif name.startswith("Site Cabins"):
        base = "Cabina de obra"
    else:
        base = name
    qty_str = f" x{qty}" if qty > 1 else ""
    if kva > 0:
        per_unit = " cada una" if qty > 1 else ""
        return f"• {base}{qty_str} — {kva:.0f}kVA{per_unit}"
    return f"• {base}{qty_str}"


def _standard_generator_size(kva):
    sizes = [20, 30, 45, 60, 80, 100, 125, 150, 200, 250, 300, 350, 400, 500, 650, 800, 1000, 1250]
    for size in sizes:
        if kva <= size:
            return size
    return int(((kva + 99) // 100) * 100)


def _diesel_baseline_line(data):
    breakdown = ((data or {}).get("baseline") or {}).get("breakdown") or []
    allowances = []
    for row in breakdown:
        assumed = str(row.get("assumed_gen") or "")
        match = re.search(r'(\d+(?:\.\d+)?)\s*kva', assumed, re.I)
        if not match:
            continue
        qty = int(row.get("qty") or 1)
        kva = float(match.group(1))
        name = row.get("name") or "equipment"
        allowances.append((name, qty, kva))
    if not allowances:
        return None
    total_kva = sum(qty * kva for _, qty, kva in allowances)
    rounded = _standard_generator_size(total_kva)
    if len(allowances) == 1:
        name, qty, kva = allowances[0]
        if qty > 1:
            return f"• Diesel baseline sizing: {qty} x {kva:.0f}kVA allowance (~{total_kva:.0f}kVA combined; typically round to {rounded}kVA if supplied from one set)"
        return f"• Diesel baseline sizing: {kva:.0f}kVA allowance (typically round to {rounded}kVA)"
    return f"• Diesel baseline sizing: ~{total_kva:.0f}kVA combined allowance (typically round to {rounded}kVA if supplied from one set)"


def _generator_rate_for_size(kva, region_cfg):
    rates = (region_cfg or {}).get("gen_rates") or {}
    if not rates:
        return None, None
    sizes = sorted(int(size) for size in rates)
    for size in sizes:
        if kva <= size:
            return size, rates.get(size) or rates.get(str(size))
    size = sizes[-1]
    return size, rates.get(size) or rates.get(str(size))


def _spec_generator_baseline_line(items, region_cfg=None):
    crane_items = [
        item for item in (items or [])
        if (item.get("name") or "").startswith("Tower Crane") and item.get("_gen_size_kva")
    ]
    if not crane_items:
        return None
    lines = []
    total = 0
    for item in crane_items:
        qty = int(item.get("qty") or 1)
        gen_size = float(item.get("_gen_size_kva") or 0)
        if gen_size <= 0:
            continue
        model = item.get("_model") or "tower crane"
        total += qty * gen_size
        rate_size, rate = _generator_rate_for_size(gen_size, region_cfg or UK_CONFIG)
        cur = (region_cfg or UK_CONFIG).get("currency", "£")
        rate_note = ""
        if rate:
            if rate_size and int(rate_size) != int(gen_size):
                rate_note = f" (rate: {rate_size}kVA at {cur}{rate:,.0f}/week)"
            else:
                rate_note = f" (rate: {cur}{rate:,.0f}/week)"
        if qty > 1:
            lines.append(f"{qty} x {model} at {gen_size:.0f}kVA each{rate_note}")
        else:
            lines.append(f"{model} at {gen_size:.0f}kVA{rate_note}")
    if not total:
        return None
    detail = "; ".join(lines)
    if len(crane_items) == 1 and int(crane_items[0].get("qty") or 1) == 1:
        return f"• Diesel baseline sizing from spec: {detail}"
    return f"• Diesel baseline sizing from spec: {detail}; tower cranes assumed on separate generators unless the site explicitly says otherwise"


def format_reply(items, weeks, data, recharge_source="gen", language="en", region_cfg=None):
    baseline = data.get("baseline", {})
    ampd = data.get("ampd", {})

    region_cfg = region_cfg or UK_CONFIG
    cur = data.get("_us_currency", region_cfg.get("currency", "£"))
    region_code = region_cfg.get("currency_code", "GBP")
    uses_regional_overrides = region_code != "GBP"

    gen_total = baseline.get("cost_total", 0)
    gen_co2 = baseline.get("co2_tonnes", 0)
    gen_weekly = gen_total / weeks if weeks else 0

    ampd_total = ampd.get("cost_total", 0)
    ampd_unit = ampd.get("unit_name", "Ampd BESS")
    ampd_count = ampd.get("unit_count", 1)
    ampd_weekly = ampd.get("weekly_rate", 0)
    ampd_co2 = ampd.get("co2_tonnes", 0)

    if uses_regional_overrides:
        gen_weekly = data.get("_us_gen_weekly", gen_weekly)
        gen_total = data.get("_us_gen_total", gen_total)
        ampd_weekly = data.get("_us_bess_weekly", ampd_weekly)
        ampd_total = data.get("_us_bess_total", ampd_total)

    # Show apples-to-apples all-in weekly totals, not hire-only BESS rate vs all-in diesel.
    gen_weekly = gen_total / weeks if weeks else 0
    ampd_weekly = ampd_total / weeks if weeks else 0

    savings = gen_total - ampd_total
    co2_saved = gen_co2 - ampd_co2
    ampd_label = f"{ampd_count}× {ampd_unit}" if ampd_count > 1 else ampd_unit
    fuel_display = data.get("_us_fuel_display", region_cfg.get("fuel_price_display", UK_CONFIG.get("fuel_price_display", "£1.50/L")))
    unit_reason = (
        _field_evidence_reason(items, ampd_unit or _recommended_unit_name(data))
        or _unit_reason_i18n(ampd_unit or _recommended_unit_name(data), region_code, language)
        or "Lowest weekly cost for this scenario."
    )
    recharge_label = "mains charge" if recharge_source == "mains" else "generator recharge"

    if language == "es":
        diesel_baseline_line = _spec_generator_baseline_line(items, region_cfg) or _diesel_baseline_line(data)
        recharge_label = "recarga desde red" if recharge_source == "mains" else "recarga con generador"
        lines = [
            f"✅ *Recomendación:* {ampd_label}",
            f"• Coste semanal: *{cur}{ampd_weekly:,.0f}* frente a diésel {cur}{gen_weekly:,.0f}",
            f"• Ahorro: *{cur}{savings:,.0f}* y *{co2_saved:.1f}t CO2* durante {int(round(weeks))} semanas",
            f"• Por qué: {unit_reason}",
            "",
            "*Comparación rápida*",
            f"• Generador diésel: {cur}{gen_total:,.0f} total",
            f"• Ampd BESS ({recharge_label}): {cur}{ampd_total:,.0f} total",
            "",
            "*Escenario*",
        ]
        if diesel_baseline_line:
            lines.insert(8, diesel_baseline_line)
        for item in items:
            lines.append(_display_item_i18n(item, language))
        if savings < 0:
            lines.append("")
            lines.append("El diésel sale más barato en esta duración, pero puedo revisar una contratación más larga o recarga desde red.")
        lines.extend(_next_step_options_i18n(items, weeks, recharge_source, language=language))
        lines.extend(["", "Responde *CONTACTO* y el equipo de Ampd puede revisar este caso."])
        return "\n".join(lines)

    diesel_baseline_line = _spec_generator_baseline_line(items, region_cfg) or _diesel_baseline_line(data)
    screening_lines = _loadout_screening_lines(items)
    field_evidence_lines, screening_lines = _split_field_evidence_first(screening_lines)

    lines = []
    if field_evidence_lines:
        lines.extend(["*Field evidence first*", *field_evidence_lines, ""])
    lines.extend([
        f"✅ *Recommendation:* {ampd_label}",
        f"• Weekly cost: *{cur}{ampd_weekly:,.0f}* vs diesel {cur}{gen_weekly:,.0f}",
        _savings_summary_line(cur, savings, co2_saved, weeks),
        f"• Why: {unit_reason}",
        "",
        "*Quick compare*",
        f"• Diesel generator: {cur}{gen_total:,.0f} total",
        f"• Ampd BESS ({recharge_label}): {cur}{ampd_total:,.0f} total",
        "",
        "*Scenario*",
    ])
    if diesel_baseline_line:
        insert_at = lines.index("*Scenario*") - 1
        lines.insert(insert_at, diesel_baseline_line)
    for item in items:
        lines.append(_display_item(item))
    if screening_lines:
        lines.extend(["", "*Screening basis*", *screening_lines])
    if savings < 0:
        lines.append("")
        lines.append("Diesel is cheaper on this duration, but I can check a longer hire or mains recharge.")
    lines.extend(_next_step_options(items, weeks, recharge_source))
    lines.extend(["", _regional_copy(region_code)["contact"]])
    return "\n".join(lines)


def format_both_reply(items, weeks, data_gen, data_grid, region_cfg, language="en"):
    """Show generator baseline + both BESS recharge options in one reply."""
    cur = region_cfg.get("currency", "£")
    uses_regional_overrides = region_cfg.get("currency_code") != "GBP"

    baseline = data_gen.get("baseline", {})
    gen_total = data_gen.get("_us_gen_total", baseline.get("cost_total", 0)) if uses_regional_overrides else baseline.get("cost_total", 0)
    gen_weekly = gen_total / weeks if weeks else 0

    ag = data_gen.get("ampd", {})
    ag_total = data_gen.get("_us_bess_total", ag.get("cost_total", 0)) if uses_regional_overrides else ag.get("cost_total", 0)
    ag_weekly = data_gen.get("_us_bess_weekly", ag.get("weekly_rate", 0)) if uses_regional_overrides else ag.get("weekly_rate", 0)
    ag_unit = ag.get("unit_name", "Ampd BESS")
    ag_count = ag.get("unit_count", 1)
    ag_label = f"{ag_count}× {ag_unit}" if ag_count > 1 else ag_unit

    am = data_grid.get("ampd", {})
    am_total = data_grid.get("_us_bess_total", am.get("cost_total", 0)) if uses_regional_overrides else am.get("cost_total", 0)
    am_weekly = data_grid.get("_us_bess_weekly", am.get("weekly_rate", 0)) if uses_regional_overrides else am.get("weekly_rate", 0)

    # Show apples-to-apples all-in weekly totals, not hire-only BESS rate vs all-in diesel.
    gen_weekly = gen_total / weeks if weeks else 0
    ag_weekly = ag_total / weeks if weeks else 0
    am_weekly = am_total / weeks if weeks else 0

    savings_gen = gen_total - ag_total
    savings_grid = gen_total - am_total
    best_mode = "mains recharge" if am_total <= ag_total else "generator recharge"
    best_total = min(ag_total, am_total)
    best_weekly = am_weekly if am_total <= ag_total else ag_weekly

    if language == "es":
        best_mode_es = "recarga desde red" if best_mode == "mains recharge" else "recarga con generador"
        lines = [
            f"✅ *Recomendación:* {ag_label} con {best_mode_es}",
            f"• Coste semanal: *{cur}{best_weekly:,.0f}* frente a diésel {cur}{gen_weekly:,.0f}",
            f"• Ahorro: *{cur}{(gen_total - best_total):,.0f}* durante {int(round(weeks))} semanas",
            f"• Por qué: {_unit_reason_i18n(ag_unit or _recommended_unit_name(data_gen), region_cfg.get('currency_code', 'GBP'), language) or 'Mejor valor entre las opciones de recarga.'}",
            "",
            "*Comparación de recarga*",
            f"• Generador diésel: {cur}{gen_total:,.0f} total",
            f"• Ampd + recarga con generador: {cur}{ag_total:,.0f} total, ahorra {cur}{savings_gen:,.0f}",
            f"• Ampd + recarga desde red: {cur}{am_total:,.0f} total, ahorra {cur}{savings_grid:,.0f}",
        ]
        lines.extend(_next_step_options_i18n(items, weeks, "mains" if best_mode == "mains recharge" else "gen", compare_mode=True, language=language))
        lines.extend(["", "Responde *CONTACTO* y el equipo de Ampd puede revisar este caso."])
        return "\n".join(lines)

    screening_lines = _loadout_screening_lines(items)
    field_evidence_lines, screening_lines = _split_field_evidence_first(screening_lines)

    lines = []
    if field_evidence_lines:
        lines.extend(["*Field evidence first*", *field_evidence_lines, ""])
    lines.extend([
        f"✅ *Recommendation:* {ag_label} with {best_mode}",
        f"• Weekly cost: *{cur}{best_weekly:,.0f}* vs diesel {cur}{gen_weekly:,.0f}",
        f"• Saves: *{cur}{(gen_total - best_total):,.0f}* over {int(round(weeks))} weeks",
        f"• Why: {_field_evidence_reason(items, ag_unit or _recommended_unit_name(data_gen)) or _unit_reason(ag_unit or _recommended_unit_name(data_gen), region_cfg.get('currency_code', 'GBP')) or 'Best value across both recharge options.'}",
        "",
        "*Recharge comparison*",
        f"• Diesel generator: {cur}{gen_total:,.0f} total",
        f"• Ampd + generator recharge: {cur}{ag_total:,.0f} total, saves {cur}{savings_gen:,.0f}",
        f"• Ampd + mains recharge: {cur}{am_total:,.0f} total, saves {cur}{savings_grid:,.0f}",
    ])
    if screening_lines:
        lines.extend(["", "*Screening basis*", *screening_lines])
    lines.extend(_next_step_options(items, weeks, "mains" if best_mode == "mains recharge" else "gen", compare_mode=True))
    lines.extend(["", _regional_copy(region_cfg.get('currency_code', 'GBP'))["contact"]])
    return "\n".join(lines)


# ─── Meta Cloud API: Send Message ─────────────────────────────────────────────
def send_whatsapp_message(to_number, text):
    """Send a WhatsApp message via Meta Cloud API."""
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        print("[Surge] META credentials not set — cannot send message", flush=True)
        return

    url = f"https://graph.facebook.com/v19.0/{META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[Surge] Sent to {to_number}: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"[Surge] Send error: {e}", flush=True)


# ─── Conversation State ────────────────────────────────────────────────────────
# In-memory state machine per phone number. Tracks two possible stages:
#   "awaiting_contact"  — user typed INFO, bot is waiting for name/email/phone
#   "awaiting_recharge" — loads parsed, bot is waiting for mains vs generator answer
conversation_state = {}

NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# Admin credentials for /leads and /conversations
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")


def require_auth(f):
    """Basic auth decorator for admin routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not ADMIN_USER or not ADMIN_PASS or not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
            return Response(
                "Unauthorised", 401,
                {"WWW-Authenticate": 'Basic realm="Surge Admin"'}
            )
        return f(*args, **kwargs)
    return decorated
_RUNTIME_DIR = os.environ.get("SURGE_RUNTIME_DIR", "/var/lib/surge")
LEADS_FILE   = os.environ.get("SURGE_LEADS_FILE", os.path.join(_RUNTIME_DIR, "leads.json"))
CONVOS_FILE  = os.environ.get("SURGE_CONVOS_FILE", os.path.join(_RUNTIME_DIR, "conversations.json"))
JOBS_FILE    = os.environ.get("SURGE_JOBS_FILE", os.path.join(_RUNTIME_DIR, "jobs.json"))
ARTIFACTS_FILE = os.environ.get(
    "SURGE_ARTIFACTS_FILE",
    os.path.join(_RUNTIME_DIR, "artifacts.json"),
)


def _job_display_id(job):
    """Short human-facing ID for Discord/WhatsApp; long job id remains internal."""
    if not job:
        return None
    return job.get("display_id") or job.get("id")


def _display_id_number(display_id):
    match = re.search(r'(\d+)$', display_id or '')
    return int(match.group(1)) if match else 0


def _next_display_id(jobs):
    used = {_display_id_number(job.get("display_id")) for job in jobs if job.get("display_id")}
    n = 1
    while n in used:
        n += 1
    return f"S-{n:04d}"


def _find_job_by_reference(user_jobs, reference):
    ref = (reference or "").strip().upper()
    if not ref:
        return None
    for job in user_jobs:
        if ref == (job.get("display_id") or "").upper() or ref == (job.get("id") or "").upper():
            return job
    return None


def _read_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[Surge] JSON read error for {path}: {e}")
    return default


def _write_json_file(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        print(f"[Surge] JSON write error for {path}: {e}")
        return False


def _job_items_signature(items):
    parts = []
    for item in sorted(items or [], key=lambda i: (i.get("name", ""), float(i.get("kva") or 0))):
        parts.append(f"{item.get('name')}:{item.get('qty', 1)}:{float(item.get('kva') or 0):.1f}")
    return "|".join(parts)


def _job_similarity_score(items_a, items_b):
    sig_a = {(i.get("name"), round(float(i.get("kva") or 0), -1)) for i in (items_a or [])}
    sig_b = {(i.get("name"), round(float(i.get("kva") or 0), -1)) for i in (items_b or [])}
    if not sig_a or not sig_b:
        return 0.0
    overlap = len(sig_a & sig_b)
    union = len(sig_a | sig_b) or 1
    qty_a = sum(i.get("qty", 1) for i in (items_a or []))
    qty_b = sum(i.get("qty", 1) for i in (items_b or []))
    qty_score = 1.0 - min(abs(qty_a - qty_b) / max(qty_a, qty_b, 1), 1.0)
    return round((overlap / union * 0.75) + (qty_score * 0.25), 3)


def find_similar_jobs(items, exclude_job_id=None, limit=3):
    jobs = _read_json_file(JOBS_FILE, [])
    scored = []
    for job in jobs:
        if exclude_job_id and job.get("id") == exclude_job_id:
            continue
        latest = (job.get("versions") or [])[-1] if job.get("versions") else {}
        score = _job_similarity_score(items, latest.get("items") or job.get("items") or [])
        if score >= 0.45:
            scored.append((score, job, latest))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [
        {
            "score": score,
            "job_id": job.get("id"),
            "title": job.get("title"),
            "created_by": job.get("created_by"),
            "latest_version": latest.get("version"),
            "items": latest.get("items") or job.get("items") or [],
            "weeks": latest.get("weeks"),
            "recharge_source": latest.get("recharge_source"),
            "recommended_unit": latest.get("recommended_unit"),
            "savings": latest.get("savings"),
            "co2_saved": latest.get("co2_saved"),
        }
        for score, job, latest in scored[:limit]
    ]


def _job_title(items):
    if not items:
        return "Untitled site power job"
    labels = []
    for item in items[:3]:
        labels.append(_display_item(item).replace("• ", ""))
    return ", ".join(labels)


def save_job_version(from_number, items, weeks, recharge_source, region_cfg, data, source_text="", job_id=None):
    """Persist a calculation as a versioned job record for future assumptions/benchmarking."""
    if not from_number:
        return None
    jobs = _read_json_file(JOBS_FILE, [])
    now = datetime.utcnow().isoformat()
    baseline = data.get("baseline", {})
    ampd = data.get("ampd", {})
    cur = data.get("_us_currency", region_cfg.get("currency", "£"))
    gen_total = data.get("_us_gen_total", baseline.get("cost_total", 0))
    ampd_total = data.get("_us_bess_total", ampd.get("cost_total", 0))
    version = {
        "version": 1,
        "timestamp": now,
        "source_text": source_text,
        "items": _serialize_items(items),
        "weeks": weeks,
        "recharge_source": recharge_source,
        "region": region_cfg.get("currency_code", "GBP"),
        "currency": cur,
        "generator_kva": _generator_size_label(data),
        "recommended_unit": ampd.get("unit_name") or _recommended_unit_name(data),
        "unit_count": ampd.get("unit_count", 1),
        "generator_total": gen_total,
        "ampd_total": ampd_total,
        "savings": gen_total - ampd_total,
        "co2_saved": baseline.get("co2_tonnes", 0) - ampd.get("co2_tonnes", 0),
        "assumptions": _assumption_lines(data, weeks, recharge_source, data.get("_us_fuel_display", region_cfg.get("fuel_price_display", ""))),
    }

    job = None
    if job_id:
        job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        # Reuse the latest open job for this person if the equipment signature is unchanged.
        sig = _job_items_signature(items)
        for candidate in reversed(jobs):
            if candidate.get("created_by") != from_number:
                continue
            latest = (candidate.get("versions") or [])[-1] if candidate.get("versions") else {}
            if _job_items_signature(latest.get("items") or []) == sig:
                job = candidate
                break
    if not job:
        job = {
            "id": f"job_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            "display_id": _next_display_id(jobs),
            "created_at": now,
            "updated_at": now,
            "created_by": from_number,
            "title": _job_title(items),
            "items": _serialize_items(items),
            "versions": [],
        }
        jobs.append(job)

    version["version"] = len(job.get("versions") or []) + 1
    similar = find_similar_jobs(items, exclude_job_id=job.get("id"), limit=3)
    version["similar_jobs"] = similar
    job.setdefault("versions", []).append(version)
    job["updated_at"] = now
    job["title"] = _job_title(items)
    job["items"] = _serialize_items(items)
    if _write_json_file(JOBS_FILE, jobs):
        return job
    return None


def _artifacts_by_job():
    artifacts = _read_json_file(ARTIFACTS_FILE, [])
    grouped = {}
    for artifact in artifacts:
        job_id = artifact.get("job_id")
        if not job_id:
            continue
        grouped.setdefault(job_id, []).append(artifact)
    return grouped


def _memory_context_line(job):
    if not job:
        return None
    latest = (job.get("versions") or [])[-1] if job.get("versions") else {}
    similar = latest.get("similar_jobs") or []
    bits = [f"Saved as {_job_display_id(job)} v{latest.get('version')}"]
    artifact_count = len(_artifacts_by_job().get(job.get("id"), []))
    if artifact_count:
        bits.append(f"{artifact_count} saved artifact(s)")
    if similar:
        best = similar[0]
        bits.append(f"closest previous case: {best.get('title')} ({int(best.get('score', 0)*100)}% match)")
    return "🧠 " + "; ".join(bits) + "."


def save_learning_feedback(from_number, body):
    """Attach supervised feedback to a saved Surge job without changing assumptions automatically."""
    if not from_number:
        return None
    jobs = _read_json_file(JOBS_FILE, [])
    user_jobs = [j for j in jobs if j.get("created_by") == from_number]
    if not user_jobs:
        return "No saved Surge job to attach learning to yet. Run a scenario first, then reply `LEARN: ...`."

    text = re.sub(r'^\s*(learn|feedback)\s*:?\s*', '', body, flags=re.I).strip()
    job_id_match = re.search(r'\b(?:job_\d+|S-\d{1,6})\b', text, re.I)
    job = None
    if job_id_match:
        wanted = job_id_match.group(0)
        job = _find_job_by_reference(user_jobs, wanted)
        text = text.replace(wanted, '').strip(" :-")
    if not job:
        job = sorted(user_jobs, key=lambda j: j.get("updated_at", ""), reverse=True)[0]

    outcome = None
    outcome_match = re.search(r'\b(won|lost|live|quoted|rejected|wrong|correct|approved)\b', text, re.I)
    if outcome_match:
        outcome = outcome_match.group(1).lower()

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "from": from_number,
        "outcome": outcome,
        "note": text,
        "mode": "supervised_feedback",
    }
    job.setdefault("learning_feedback", []).append(entry)
    latest = (job.get("versions") or [])[-1] if job.get("versions") else None
    if latest is not None:
        latest.setdefault("learning_feedback", []).append(entry)
    job["updated_at"] = entry["timestamp"]
    if not _write_json_file(JOBS_FILE, jobs):
        return "I couldn't save that learning note — storage write failed."
    label = f" ({outcome})" if outcome else ""
    return f"🧠 Saved learning feedback{label} against {_job_display_id(job)}: {job.get('title')}."


def log_message(from_number, direction, text):
    """Log every message (inbound + outbound) to conversations.json."""
    try:
        if os.path.exists(CONVOS_FILE):
            with open(CONVOS_FILE, "r") as f:
                convos = json.load(f)
        else:
            convos = {}

        if from_number not in convos:
            convos[from_number] = []

        convos[from_number].append({
            "ts": datetime.utcnow().isoformat(),
            "direction": direction,  # "in" or "out"
            "text": text,
        })

        with open(CONVOS_FILE, "w") as f:
            json.dump(convos, f, indent=2)
    except Exception as e:
        print(f"[Surge] Convo log error: {e}")


def save_lead(from_number, contact_details):
    """Persist lead to JSON, then email the Ampd team via Resend with full conversation history."""
    display_number = from_number

    try:
        if os.path.exists(LEADS_FILE):
            with open(LEADS_FILE, "r") as f:
                leads = json.load(f)
        else:
            leads = []

        leads.append({
            "timestamp": datetime.utcnow().isoformat(),
            "whatsapp": display_number,
            "contact": contact_details,
            "notified": False,
        })

        with open(LEADS_FILE, "w") as f:
            json.dump(leads, f, indent=2)

        print(f"[Surge] Lead saved: {display_number} — {contact_details}")
    except Exception as e:
        print(f"[Surge] ERROR saving lead to JSON: {e}")

    # Build conversation history for email
    convo_html = ""
    try:
        if os.path.exists(CONVOS_FILE):
            with open(CONVOS_FILE, "r") as f:
                convos = json.load(f)
            messages = convos.get(from_number, [])
            if messages:
                rows = ""
                for m in messages:
                    direction = m.get("direction", "in")
                    bubble_color = "#f0fdf4" if direction == "out" else "#f8fafc"
                    label = "Surge" if direction == "out" else "User"
                    label_color = "#16a34a" if direction == "out" else "#0f172a"
                    ts = m.get("ts", "")[:16].replace("T", " ")
                    text = m.get("text", "").replace("\n", "<br>")
                    rows += f"""
                    <tr>
                      <td style="padding:10px 12px;background:{bubble_color};border-bottom:1px solid #e2e8f0;vertical-align:top;width:60px;">
                        <strong style="color:{label_color};font-size:12px;">{label}</strong><br>
                        <span style="color:#94a3b8;font-size:11px;">{ts}</span>
                      </td>
                      <td style="padding:10px 12px;background:{bubble_color};border-bottom:1px solid #e2e8f0;font-size:13px;color:#334155;">{text}</td>
                    </tr>"""
                convo_html = f"""
                <h3 style="color:#0f172a;margin-top:32px;">💬 Conversation History</h3>
                <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
                  {rows}
                </table>"""
    except Exception as e:
        print(f"[Surge] Convo history error: {e}")

    # Send via Resend API
    try:
        html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:#0f172a;padding:24px 32px;">
      <h1 style="color:#ffffff;margin:0;font-size:22px;">⚡ New Surge Lead</h1>
      <p style="color:#94a3b8;margin:4px 0 0;font-size:14px;">Someone wants to be contacted via WhatsApp</p>
    </div>

    <!-- Body -->
    <div style="padding:32px;">
      <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
        <tr>
          <td style="padding:12px 16px;background:#f8fafc;font-weight:600;color:#64748b;font-size:13px;text-transform:uppercase;letter-spacing:0.05em;width:140px;border-bottom:1px solid #e2e8f0;">WhatsApp</td>
          <td style="padding:12px 16px;background:#f8fafc;font-size:15px;color:#0f172a;border-bottom:1px solid #e2e8f0;">{display_number}</td>
        </tr>
        <tr>
          <td style="padding:12px 16px;font-weight:600;color:#64748b;font-size:13px;text-transform:uppercase;letter-spacing:0.05em;">Contact</td>
          <td style="padding:12px 16px;font-size:15px;color:#0f172a;">{contact_details}</td>
        </tr>
      </table>

      {convo_html}
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="margin:0;color:#94a3b8;font-size:12px;">Surge by Ampd Energy ⚡ — {datetime.utcnow().strftime("%d %b %Y %H:%M")} UTC</p>
    </div>

  </div>
</body>
</html>"""

        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": "Surge <surge@getjoule.co.uk>",
                "reply_to": "tom@getjoule.co.uk",
                "to": [NOTIFY_EMAIL],
                "subject": f"⚡ New Surge Lead — {contact_details[:40]}",
                "html": html,
            },
            timeout=10,
        )
        resp.raise_for_status()
        print(f"[Surge] Lead email sent via Resend ✅")
    except Exception as e:
        print(f"[Surge] Resend email failed: {e}")


INFO_TEXT = {
    "GBP": (
        "⚡ Nice one. Drop your name plus email or mobile below and the Ampd team will pick it up. 👇"
    ),
    "USD": (
        "⚡ Nice. Send your name plus email or phone number below and the Ampd team will reach out. 👇"
    ),
    "CAD": (
        "⚡ Nice. Send your name plus email or phone number below and the Ampd team can pick this up for Canada. 👇"
    ),
}

INFO_TEXT_LANG = {
    "es": "⚡ Perfecto. Envíame tu nombre y email o móvil, y el equipo de Ampd lo revisará. 👇",
}

HELP_TEXT = {
    "GBP": (
        "👋 I'm Surge, Ampd Energy's site power advisor.\n\n"
        "Send whatever you know about the job and I'll guide the rest.\n\n"
        "Try: *2 tower cranes 160kVA 52 weeks mains*\n"
        "or simply: *tower cranes*"
    ),
    "USD": (
        "👋 I'm Surge, Ampd Energy's site power advisor.\n\n"
        "Send whatever you know about the job and I'll guide the rest.\n\n"
        "Try: *2 tower cranes 160kVA 52 weeks mains*\n"
        "or simply: *tower cranes*"
    ),
    "CAD": (
        "👋 I'm Surge, Ampd Energy's site power advisor.\n\n"
        "Send whatever you know about the Canadian job and I'll guide the rest.\n\n"
        "Try: *Toronto 2 tower cranes 160kVA 52 weeks mains*\n"
        "or simply: *tower cranes in Canada*"
    ),
}

HELP_TEXT_LANG = {
    "es": (
        "👋 Soy Surge, el asesor de potencia de obra de Ampd Energy.\n\n"
        "Envíame lo que sepas del proyecto y te guío con el resto.\n\n"
        "Prueba: *2 grúas torre 160kVA 52 semanas red*\n"
        "o simplemente: *grúas torre*"
    ),
}


def _find_clarifications(body, items, parse_meta):
    missing = []
    text_lower = body.lower()

    plural_hints = [
        ("Tower Crane", ["tower cranes", "cranes"]),
        ("Passenger Hoist", ["hoists", "passenger hoists", "goods hoists"]),
        ("Mast Climber", ["mast climbers", "climbers"]),
        ("Site Cabins", ["cabins", "welfare cabins", "site cabins", "office units"]),
        ("Welding Set", ["welders", "welding sets"]),
        ("EV Car Charger", ["chargers", "ev chargers"]),
        ("Silo Mixer", ["mixers", "silos"]),
    ]
    explicit_qty_in_text = bool(
        re.search(r'\b(?:[x×]\s*)?\d+\s*(?:[x×]\s*)?(tower cranes?|cranes|passenger hoists?|goods hoists?|hoists|mast climbers?|climbers|cabins|welfare cabins|site cabins|office units|welders|welding sets|chargers|ev chargers|mixers|silos)\b', text_lower)
        or extract_crane_qty(body)
    )

    for item in items or []:
        if item.get("qty", 1) != 1 or explicit_qty_in_text:
            continue
        for item_prefix, hints in plural_hints:
            if not item["name"].startswith(item_prefix):
                continue
            for hint in hints:
                if hint in text_lower:
                    missing.append("qty")
                    break

    for item in items or []:
        if item["name"].startswith("Tower Crane") and item.get("qty", 1) >= 2 and not item.get("kva"):
            missing.append("crane_load")
            break

    has_crane = any((item.get("name") or "").startswith("Tower Crane") for item in items or [])
    if has_crane and parse_meta.get("unmatched_manufacturer_models"):
        missing.append("exact_model_spec")

    if has_crane and parse_meta.get("manufacturer_matched") and not parse_meta.get("power_path_explicit"):
        missing.append("power_path")

    if not parse_meta.get("duration_explicit"):
        missing.append("duration")

    if not parse_meta.get("recharge_explicit"):
        missing.append("recharge")

    ordered = []
    for key in ("exact_model_spec", "qty", "crane_load", "power_path", "duration", "recharge"):
        if key in missing and key not in ordered:
            ordered.append(key)
    has_generator_allowance = any(float(item.get("kva") or 0) > 0 for item in items or [])
    if has_generator_allowance and set(ordered).issubset({"duration", "recharge"}) and not has_crane:
        return []
    return ordered


def _clarification_prompt(missing, language="en"):
    if not missing:
        return None
    if language == "es":
        prompt_map = {
            "exact_model_spec": "Ese modelo de grúa no coincide exactamente con la base de datos. ¿Puedes confirmar el modelo exacto o enviar la ficha técnica/plano antes de dimensionarlo?",
            "qty": "¿Cuántas unidades son? Por ejemplo: *2 grúas torre*.",
            "crane_load": "¿Carga aproximada por grúa? Por ejemplo: *160kVA*. Si no estás seguro, di *media*.",
            "power_path": "¿Qué alimentará realmente las grúas: salida Ampd, generador directo, red directa o cuadro de distribución? ¿Y la Ampd recargará desde red o generador?",
            "duration": "¿Durante cuánto tiempo es el alquiler? Por ejemplo: *52 semanas*.",
            "recharge": "¿La batería recargará desde *red* o con *generador*?",
        }
        return prompt_map.get(missing[0], "Una pregunta rápida para no adivinar — ¿qué dato uso?")
    prompt_map = {
        "exact_model_spec": "One of those crane models does not exactly match the manufacturer database. Can you confirm the exact model/variant or send the spec sheet/drawing before I size it?",
        "qty": "How many units is that? For example: *2 tower cranes*.",
        "crane_load": "Approx load per crane? For example: *160kVA*. If you're not sure, say *medium*.",
        "power_path": "What will actually feed the crane(s): Ampd output, generator direct, mains direct, or an existing distribution board? And will the Ampd recharge from mains or generator?",
        "duration": "How long is the hire? For example: *52 weeks*.",
        "recharge": "Will the battery recharge from *mains* or a *generator*?",
    }
    return prompt_map.get(missing[0], "Quick one so I don't guess — what should I use?")


def _can_screen_with_default_assumptions(missing, items):
    """Keep demo flow moving when plant/load is clear but timing assumptions are missing."""
    if not missing or not items:
        return False
    return set(missing).issubset({"duration", "recharge"})


def _default_assumption_note(defaulted, language="en"):
    if not defaulted:
        return None
    if language == "es":
        labels = {"duration": "52 semanas", "recharge": "recarga con generador"}
        used = ", ".join(labels[key] for key in defaulted if key in labels)
        return f"Nota: he usado {used} como supuesto inicial. Dime la duración o la recarga real y lo recalculo."
    labels = {"duration": "52 weeks", "recharge": "generator recharge"}
    used = ", ".join(labels[key] for key in defaulted if key in labels)
    return f"Note: I’ve used {used} as a first-pass assumption. Give me the real duration or recharge source and I’ll rerun it."


def _equipment_reply_from_missing(missing, original_body):
    """Map a bare numeric reply onto the detail Surge actually asked for."""
    original_lower = (original_body or "").lower()
    if "qty" not in (missing or []):
        return None
    if "crane" in original_lower:
        return "tower cranes"
    if "hoist" in original_lower:
        return "passenger hoists"
    if "mast" in original_lower or "climber" in original_lower:
        return "mast climbers"
    if "cabin" in original_lower or "welfare" in original_lower:
        return "welfare cabins"
    return None


def _merge_pending_detail_reply(pending, reply):
    """Merge a clarification answer without turning every bare number into weeks."""
    reply = reply.strip()
    original = pending.get("body", "")
    missing = pending.get("missing", [])

    equipment_patterns = {
        "tower cranes": r'\b(?:tower\s+cranes?|cranes?)\b',
        "passenger hoists": r'\b(?:passenger\s+hoists?|goods\s+hoists?|hoists?)\b',
        "mast climbers": r'\b(?:mast\s+climbers?|climbers?)\b',
        "welfare cabins": r'\b(?:welfare\s+cabins?|site\s+cabins?|cabins?)\b',
    }

    if "qty" in missing:
        equipment = _equipment_reply_from_missing(missing, original)
        pattern = equipment_patterns.get(equipment)
        if equipment and pattern and re.search(pattern, original, re.I):
            # Accept both bare replies ("3") and natural replies ("3 tower cranes").
            qty_match = re.search(r'\b(?:[x×]\s*)?(\d+)\s*(?:[x×]\s*)?(?:tower\s+cranes?|cranes?|passenger\s+hoists?|goods\s+hoists?|hoists?|mast\s+climbers?|climbers?|welfare\s+cabins?|site\s+cabins?|cabins?)?\b', reply, re.I)
            if qty_match:
                qty_phrase = f"{qty_match.group(1)} {equipment}"
                return re.sub(pattern, qty_phrase, original, count=1, flags=re.I)

    if re.fullmatch(r'\d+(?:\.\d+)?', reply):
        if "duration" in missing:
            return f"{original}, {reply} weeks".strip(", ")

    if "crane_load" in missing:
        kva_match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*kva', reply, re.I)
        kw_match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*kw', reply, re.I)
        size_match = re.fullmatch(r'(small|medium|large)', reply, re.I)
        if kva_match or kw_match:
            load_phrase = f"{kva_match.group(1) if kva_match else kw_match.group(1)}{'kVA' if kva_match else 'kW'}"
            return re.sub(r'\b((?:\d+\s*)?(?:tower\s+cranes?|cranes?))\b', rf'\1 {load_phrase}', original, count=1, flags=re.I)
        if size_match:
            size_defaults = {"small": "100kVA", "medium": "160kVA", "large": "250kVA"}
            load_phrase = size_defaults[size_match.group(1).lower()]
            return re.sub(r'\b((?:\d+\s*)?(?:tower\s+cranes?|cranes?))\b', rf'\1 {load_phrase}', original, count=1, flags=re.I)

    return f"{original}, {reply}".strip(", ")


def handle_message(body, from_number=None):
    body = body.strip()
    # Demo override — prefix [US]/[UK]/[CA] forces regional config regardless of number.
    if re.match(r'^\[US\]\s*', body, re.I):
        body = re.sub(r'^\[US\]\s*', '', body, flags=re.I).strip()
        region_cfg = US_CONFIG
    elif re.match(r'^\[UK\]\s*', body, re.I):
        body = re.sub(r'^\[UK\]\s*', '', body, flags=re.I).strip()
        region_cfg = UK_CONFIG
    elif re.match(r'^\[(?:CA|CANADA)\]\s*', body, re.I):
        body = re.sub(r'^\[(?:CA|CANADA)\]\s*', '', body, flags=re.I).strip()
        region_cfg = CA_CONFIG
    else:
        region_cfg = detect_region_config_from_text(body) or get_region_config(from_number or "")
    body_upper = body.upper()

    pending = conversation_state.get(from_number) if from_number else None
    text_region_cfg = detect_region_config_from_text(body)
    region_cfg = text_region_cfg or (pending or {}).get("region_cfg", region_cfg)
    region_code = region_cfg.get("currency_code", "GBP")
    language = _detect_language(body, (pending or {}).get("language", "en"))
    body = _strip_language_command(body)
    parse_body = _normalise_language_input(body, language)
    if from_number and language != "en":
        conversation_state.setdefault(from_number, {})["language"] = language

    if re.match(r'^\s*(LEARN|FEEDBACK)\b', body, re.I):
        return save_learning_feedback(from_number or "test-user", body)

    if re.match(r'^\s*(LANG|IDIOMA)\b', body_upper, re.I) and not body:
        return f"Language set to {LANGUAGE_NAMES.get(language, 'English')}." if language != "es" else "Idioma configurado: Español."

    if body_upper in ("JOBS", "MEMORY"):
        jobs = _read_json_file(JOBS_FILE, [])
        user_jobs = [j for j in jobs if j.get("created_by") == (from_number or "test-user")]
        if not user_jobs:
            return "No saved Surge jobs for this conversation yet. Send a site scenario and I’ll start building the memory."
        recent = sorted(user_jobs, key=lambda j: j.get("updated_at", ""), reverse=True)[:5]
        lines = ["🧠 *Saved Surge jobs*"]
        for job in recent:
            latest = (job.get("versions") or [])[-1] if job.get("versions") else {}
            cur = latest.get("currency", "£")
            lines.append(f"• {_job_display_id(job)}: {job.get('title')} — v{latest.get('version')}, saves {cur}{latest.get('savings', 0):,.0f}")
        return "\n".join(lines)

    if body_upper in ("INFO", "TALK", "CONTACT"):
        if from_number:
            conversation_state[from_number] = {"stage": "awaiting_contact", "region_cfg": region_cfg, "language": language}
        return INFO_TEXT_LANG.get(language) or INFO_TEXT[region_code]

    if body_upper in ("CONTACTO", "HABLAR", "INFO") and language == "es":
        if from_number:
            conversation_state[from_number] = {"stage": "awaiting_contact", "region_cfg": region_cfg, "language": language}
        return INFO_TEXT_LANG["es"]

    if pending and pending.get("stage") == "awaiting_contact":
        if from_number:
            del conversation_state[from_number]
        threading.Thread(
            target=save_lead,
            args=(from_number or "unknown", body),
            daemon=True
        ).start()
        if region_code == "USD":
            return "✅ Got it. I've passed your details to the Ampd team. They'll be in touch soon."
        if language == "es":
            return "✅ Listo. He pasado tus datos al equipo de Ampd. Se pondrán en contacto pronto."
        return "✅ Sorted. I've passed your details to the Ampd team. They'll be in touch shortly."

    if pending and pending.get("stage") == "awaiting_details":
        body = _merge_pending_detail_reply(pending, parse_body)
        parse_body = body
        if from_number:
            del conversation_state[from_number]
        pending = None

    scenario = pending.get("scenario") if pending else None
    followup = _apply_followup(parse_body, scenario)
    if followup:
        items = followup["items"]
        weeks = followup["weeks"]
        recharge_source = followup["recharge_source"]
        parse_meta = {"duration_explicit": True, "recharge_explicit": True}
        compare_mode = followup.get("compare_mode", False)
    else:
        items, weeks, recharge_source, parse_meta = parse_message(parse_body)
        compare_mode = bool(re.search(r'\b(compare|vs|versus|comparar|compara)\b', parse_body, re.I) and re.search(r'\b(mains|grid|gen|generator)\b', parse_body, re.I))

    if not items:
        return HELP_TEXT_LANG.get(language) or HELP_TEXT[region_code]

    missing = _find_clarifications(parse_body, items, parse_meta)
    if missing:
        if _can_screen_with_default_assumptions(missing, items):
            defaulted = list(missing)
            if "duration" in defaulted:
                weeks = 52
                parse_meta["duration_explicit"] = True
            if "recharge" in defaulted:
                recharge_source = "gen"
                parse_meta["recharge_explicit"] = True
        else:
            if from_number:
                conversation_state[from_number] = {
                    "stage": "awaiting_details",
                    "body": parse_body,
                    "missing": missing,
                    "region_cfg": region_cfg,
                    "scenario": scenario,
                    "language": language,
                }
            return _clarification_prompt(missing, language)
    else:
        defaulted = []

    try:
        data_gen = apply_regional_overrides(call_loadout(items, weeks, "gen", region=region_cfg), region_cfg, weeks)
        data_mains = apply_regional_overrides(call_loadout(items, weeks, "mains", region=region_cfg), region_cfg, weeks)
        data = data_mains if recharge_source == "mains" else data_gen
    except Exception as e:
        return f"⚠️ Couldn't reach the calculation engine right now. Try again in a moment.\n\nError: {e}"

    if from_number:
        job = save_job_version(from_number, items, weeks, recharge_source, region_cfg, data, source_text=body, job_id=(scenario or {}).get("job_id"))
        conversation_state[from_number] = {
            "stage": "ready",
            "region_cfg": region_cfg,
            "language": language,
            "scenario": _scenario_state(items, weeks, recharge_source, region_cfg, job.get("id") if job else None),
        }
    else:
        job = None

    if compare_mode:
        reply = format_both_reply(items, weeks, data_gen, data_mains, region_cfg, language=language)
    else:
        reply = format_reply(items, weeks, data, recharge_source, language=language, region_cfg=region_cfg)
    assumption_note = _default_assumption_note(defaulted, language)
    if assumption_note:
        reply = f"{reply}\n\n{assumption_note}"
    grid_upgrade_line = _grid_upgrade_screen(parse_body, region_cfg)
    if grid_upgrade_line:
        reply = f"{reply}\n\n*Infrastructure angle*\n{grid_upgrade_line}\n• Treat this as an early commercial screen, not a DNO quote."
    memory_line = _memory_context_line(job)
    if memory_line:
        reply = f"{reply}\n\n{memory_line}"
    return reply


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return "Surge is running ✅ — Surge by Ampd Energy", 200


@app.route("/healthz", methods=["GET"])
def healthz():
    """Lightweight local health check for systemd/nginx monitoring."""
    return jsonify({"ok": True, "service": "surge"})


@app.route('/privacy', methods=['GET'])
def privacy():
    policy_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'surge-privacy-policy.md')
    with open(policy_path, 'r', encoding='utf-8') as f:
        policy_html = markdown(f.read(), extensions=['tables'])
    return render_template('privacy.html', policy_html=policy_html), 200, {'Cache-Control': 'no-store'}


@app.route('/terms', methods=['GET'])
def terms():
    terms_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'surge-terms.md')
    with open(terms_path, 'r', encoding='utf-8') as f:
        policy_html = markdown(f.read(), extensions=['tables'])
    return render_template('privacy.html', policy_html=policy_html), 200, {'Cache-Control': 'no-store'}


@app.route("/webhook", methods=["GET"])
def webhook_verify():
    """Meta webhook verification (GET).

    When a webhook is first registered, Meta sends a GET with hub.mode,
    hub.verify_token, and hub.challenge. We must echo the challenge back
    if the token matches, otherwise return 403.
    """
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("[Surge] Webhook verified by Meta ✅", flush=True)
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive incoming WhatsApp messages from Meta Cloud API (POST).

    Meta sends a nested payload: entry[] → changes[] → value.messages[].
    We only handle type=="text" messages; status updates and read receipts
    are silently ignored by returning 200.
    """
    data = request.get_json(silent=True)
    if not data:
        return "OK", 200

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for message in messages:
                    if message.get("type") != "text":
                        continue
                    from_number = message["from"]  # e.g. "447516762194"
                    body = message["text"]["body"]
                    print(f"[INCOMING] From: {from_number} | Body: {body}", flush=True)
                    log_message(from_number, "in", body)

                    reply = handle_message(body, from_number)
                    log_message(from_number, "out", reply)
                    send_whatsapp_message(from_number, reply)
    except Exception as e:
        print(f"[Surge] Webhook error: {e}", flush=True)

    return "OK", 200


@app.route("/test", methods=["POST"])
def test():
    """Local testing endpoint — POST JSON {"message": "...", "from": "..."}"""
    data = request.get_json(silent=True) or {}
    body = data.get("message", "")
    from_number = data.get("from", "test-user")
    reply = handle_message(body, from_number)
    return jsonify({"reply": reply})


@app.route("/leads", methods=["GET"])
@require_auth
def leads():
    """Admin endpoint — view all captured leads as an HTML table."""
    try:
        if os.path.exists(LEADS_FILE):
            with open(LEADS_FILE, "r") as f:
                all_leads = json.load(f)
        else:
            all_leads = []
    except Exception as e:
        return f"<p>Error reading leads file: {e}</p>", 500

    rows = ""
    for lead in reversed(all_leads):
        ts      = html.escape(lead.get("timestamp", ""))
        wa      = html.escape(lead.get("whatsapp", ""))
        contact = html.escape(lead.get("contact", ""))
        rows += f"""
        <tr>
          <td style="padding:8px;border:1px solid #e2e8f0;">{ts}</td>
          <td style="padding:8px;border:1px solid #e2e8f0;">{wa}</td>
          <td style="padding:8px;border:1px solid #e2e8f0;">{contact}</td>
        </tr>"""

    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Surge Leads</title>
  <style>
    body {{ font-family: sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
    h1 {{ color: #0f172a; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    th {{ background: #0f172a; color: white; padding: 10px 8px; text-align: left; }}
    tr:hover {{ background: #f8fafc; }}
    .count {{ color: #64748b; font-size: 14px; margin-bottom: 16px; }}
  </style>
</head>
<body>
  <h1>⚡ Surge — Lead Capture</h1>
  <p class="count">{len(all_leads)} lead(s) captured</p>
  <table>
    <thead>
      <tr>
        <th>Timestamp (UTC)</th>
        <th>WhatsApp</th>
        <th>Contact Details</th>
      </tr>
    </thead>
    <tbody>
      {rows if rows else '<tr><td colspan="3" style="padding:16px;text-align:center;color:#94a3b8;">No leads yet.</td></tr>'}
    </tbody>
  </table>
</body>
</html>"""

    return page, 200, {"Content-Type": "text/html", "Cache-Control": "no-store"}


@app.route("/conversations", methods=["GET"])
@require_auth
def conversations():
    """Admin endpoint — browse all WhatsApp conversations."""
    try:
        if os.path.exists(CONVOS_FILE):
            with open(CONVOS_FILE, "r") as f:
                convos = json.load(f)
        else:
            convos = {}
    except Exception as e:
        return f"<p>Error: {e}</p>", 500

    convo_blocks = ""
    for number, messages in sorted(convos.items(), reverse=True):
        rows = ""
        for m in messages:
            direction = m.get("direction", "in")
            bubble_bg = "#dcfce7" if direction == "out" else "#f1f5f9"
            label = "⚡ Surge" if direction == "out" else "👤 User"
            ts = html.escape(m.get("ts", "")[:16].replace("T", " "))
            text = html.escape(m.get("text", "")).replace("\n", "<br>")
            rows += f'<div style="margin:6px 0;padding:10px 14px;background:{bubble_bg};border-radius:8px;font-size:13px;"><strong>{label}</strong> <span style="color:#94a3b8;font-size:11px;">{ts}</span><br>{text}</div>'

        convo_blocks += f"""
        <div style="margin-bottom:32px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
          <div style="background:#0f172a;padding:12px 16px;color:white;font-weight:600;">📱 {number}</div>
          <div style="padding:12px 16px;">{rows}</div>
        </div>"""

    page = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Surge Conversations</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px;}}h1{{color:#0f172a;}}.count{{color:#64748b;font-size:14px;}}</style>
</head>
<body>
  <h1>⚡ Surge — Conversations</h1>
  <p class="count">{len(convos)} conversation(s)</p>
  {convo_blocks if convo_blocks else '<p style="color:#94a3b8;">No conversations yet.</p>'}
</body></html>"""

    return page, 200, {"Content-Type": "text/html", "Cache-Control": "no-store"}



@app.route("/jobs", methods=["GET"])
@require_auth
def jobs():
    """Admin endpoint — view versioned Surge jobs and assumptions memory."""
    all_jobs = _read_json_file(JOBS_FILE, [])
    if request.args.get("format") == "json":
        return jsonify({"jobs": all_jobs, "count": len(all_jobs)})

    artifacts_by_job = _artifacts_by_job()
    rows = ""
    for job in sorted(all_jobs, key=lambda j: j.get("updated_at", ""), reverse=True):
        latest = (job.get("versions") or [])[-1] if job.get("versions") else {}
        cur = html.escape(str(latest.get("currency", "£")))
        assumptions = "<br>".join(html.escape(a) for a in latest.get("assumptions", []))
        similar = latest.get("similar_jobs") or []
        similar_html = "<br>".join(
            html.escape(f"{s.get('title')} — {int((s.get('score') or 0)*100)}% match")
            for s in similar
        ) or "<span style='color:#94a3b8;'>None yet</span>"
        artifacts = artifacts_by_job.get(job.get("id"), [])
        artifact_html = "<br>".join(
            f"<code>{html.escape(a.get('artifact_id', ''))}</code><br><span style='color:#64748b;'>{html.escape((a.get('title') or '')[:80])}</span>"
            for a in artifacts[-3:]
        ) or "<span style='color:#94a3b8;'>None yet</span>"
        rows += f"""
        <tr>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;"><code>{html.escape(_job_display_id(job) or '')}</code><br><span style="color:#64748b;font-size:12px;">Internal: {html.escape(job.get('id', ''))}</span><br><span style="color:#64748b;font-size:12px;">{html.escape(job.get('updated_at', '')[:16].replace('T', ' '))}</span></td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;"><strong>{html.escape(job.get('title', ''))}</strong><br><span style="color:#64748b;font-size:12px;">By {html.escape(job.get('created_by', ''))}</span></td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;">v{latest.get('version', 0)}<br>{latest.get('weeks', 0):.0f} weeks<br>{html.escape(str(latest.get('recharge_source', '')))}</td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;">{html.escape(str(latest.get('recommended_unit', '')))}<br>{cur}{latest.get('savings', 0):,.0f} saved<br>{latest.get('co2_saved', 0):.1f}t CO₂</td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;font-size:12px;">{assumptions}</td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;font-size:12px;">{similar_html}</td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;font-size:12px;">{artifact_html}</td>
        </tr>"""

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Surge Jobs</title>
<style>body{{font-family:sans-serif;max-width:1200px;margin:40px auto;padding:0 20px;color:#0f172a;}}h1{{color:#0f172a;}}table{{width:100%;border-collapse:collapse;margin-top:20px;}}th{{background:#0f172a;color:white;padding:10px;text-align:left;}}tr:hover{{background:#f8fafc;}}code{{background:#f1f5f9;padding:2px 4px;border-radius:4px;}}</style>
</head><body>
<h1>⚡ Surge — Job Memory</h1>
<p style="color:#64748b;">{len(all_jobs)} saved job(s). Each recalculation is kept as a new version so Surge can benchmark future assumptions.</p>
<table><thead><tr><th>Job</th><th>Scenario</th><th>Version</th><th>Outcome</th><th>Assumptions</th><th>Similar cases</th><th>Artifacts</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="7" style="padding:16px;text-align:center;color:#94a3b8;">No saved jobs yet.</td></tr>'}</tbody></table>
</body></html>"""
    return page, 200, {"Content-Type": "text/html", "Cache-Control": "no-store"}


@app.route("/artifacts", methods=["GET"])
@require_auth
def artifacts():
    """Admin endpoint — view saved Surge screenshots/simulation artifacts."""
    all_artifacts = _read_json_file(ARTIFACTS_FILE, [])
    if request.args.get("format") == "json":
        return jsonify({"artifacts": all_artifacts, "count": len(all_artifacts)})

    rows = ""
    for artifact in sorted(all_artifacts, key=lambda a: a.get("created_at", ""), reverse=True):
        paths = artifact.get("paths") or {}
        summary = artifact.get("summary") or {}
        rows += f"""
        <tr>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;"><code>{html.escape(artifact.get('artifact_id', ''))}</code><br><span style="color:#64748b;font-size:12px;">{html.escape(artifact.get('created_at', '')[:16].replace('T', ' '))}</span></td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;"><strong>{html.escape(artifact.get('title', ''))}</strong><br><span style="color:#64748b;font-size:12px;">Job: {html.escape(str(artifact.get('job_id') or 'unlinked'))}</span></td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;">Peak ~{summary.get('peak_load_kw', 0)}kW<br>Energy ~{summary.get('daily_load_kwh', 0)}kWh<br>Min SOC ~{summary.get('min_soc_pct', 0)}%</td>
          <td style="padding:10px;border:1px solid #e2e8f0;vertical-align:top;font-size:12px;"><code>{html.escape(paths.get('png', ''))}</code></td>
        </tr>"""

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Surge Artifacts</title>
<style>body{{font-family:sans-serif;max-width:1200px;margin:40px auto;padding:0 20px;color:#0f172a;}}h1{{color:#0f172a;}}table{{width:100%;border-collapse:collapse;margin-top:20px;}}th{{background:#0f172a;color:white;padding:10px;text-align:left;}}tr:hover{{background:#f8fafc;}}code{{background:#f1f5f9;padding:2px 4px;border-radius:4px;word-break:break-all;}}</style>
</head><body>
<h1>⚡ Surge — Simulation Artifacts</h1>
<p style="color:#64748b;">{len(all_artifacts)} saved artifact(s). If Discord attachment fails, offer email fallback after Tom confirms recipient.</p>
<table><thead><tr><th>Artifact</th><th>Scenario</th><th>Summary</th><th>PNG path</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="4" style="padding:16px;text-align:center;color:#94a3b8;">No artifacts yet.</td></tr>'}</tbody></table>
</body></html>"""
    return page, 200, {"Content-Type": "text/html", "Cache-Control": "no-store"}

@app.route("/stats", methods=["GET"])
def stats():
    """Public analytics dashboard — no auth required."""
    try:
        if os.path.exists(CONVOS_FILE):
            with open(CONVOS_FILE, "r") as f:
                convos = json.load(f)
        else:
            convos = {}
    except Exception as e:
        return f"<p>Error reading conversations: {e}</p>", 500

    total_conversations = len(convos)
    total_messages  = sum(len(msgs) for msgs in convos.values())
    inbound  = sum(1 for msgs in convos.values() for m in msgs if m.get("direction") == "in")
    outbound = sum(1 for msgs in convos.values() for m in msgs if m.get("direction") == "out")
    avg_messages = round(total_messages / total_conversations, 1) if total_conversations else 0

    # Regional split
    uk_count = us_count = other_count = 0
    for number in convos:
        num = re.sub(r'[\s\-()]', '', number)
        if num.startswith('44') or num.startswith('+44'):
            uk_count += 1
        elif num.startswith('1') and len(num) == 11:
            us_count += 1
        elif num.startswith('+1'):
            us_count += 1
        else:
            other_count += 1

    total_known = uk_count + us_count + other_count or 1
    uk_pct = round(uk_count / total_known * 100)
    us_pct = round(us_count / total_known * 100)

    # Lead capture rate
    lead_keywords = {"talk", "info"}
    leads = sum(
        1 for msgs in convos.values()
        if any(m.get("text", "").strip().lower() in lead_keywords for m in msgs)
    )
    lead_rate = round(leads / total_conversations * 100) if total_conversations else 0

    # Equipment mention counts (inbound messages only)
    EQUIP_PATTERNS = [
        ("Tower Crane",    ["tower crane", "tc", "t/c", "tower-crane", "luffing"]),
        ("Hoist",          ["passenger hoist", "hoist", "p/h", "goods hoist", "personnel hoist"]),
        ("Mast Climber",   ["mast climber", "mcwp", "mast", "facade hoist"]),
        ("Welfare Cabin",  ["welfare", "cabin", "site office", "canteen", "drying room"]),
        ("Generator",      ["generator", "gen "]),
        ("Welder",         ["welder", "welding", "weld"]),
        ("EV Charger",     ["ev charger", "ev car charger"]),
        ("Silo/Mixer",     ["silo", "mixer", "concrete"]),
    ]
    equip_counts = Counter()
    for msgs in convos.values():
        for m in msgs:
            if m.get("direction") != "in":
                continue
            txt = m.get("text", "").lower()
            for name, keywords in EQUIP_PATTERNS:
                if any(kw in txt for kw in keywords):
                    equip_counts[name] += 1
                    break  # count once per message per category

    top_equipment = equip_counts.most_common(5)

    # Conversation volume by date — last 14 days
    today = datetime.utcnow().date()
    date_range = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
    volume_by_date = Counter()
    for msgs in convos.values():
        # Count conversation started on each date (first message date)
        if msgs:
            first_ts = msgs[0].get("ts", "")[:10]
            volume_by_date[first_ts] += 1

    volume_labels = [d.strftime("%d %b") for d in date_range]
    volume_counts = [volume_by_date.get(d.isoformat(), 0) for d in date_range]

    stats_data = {
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "inbound": inbound,
        "outbound": outbound,
        "avg_messages": avg_messages,
        "uk_count": uk_count,
        "us_count": us_count,
        "other_count": other_count,
        "uk_pct": uk_pct,
        "us_pct": us_pct,
        "leads": leads,
        "lead_rate": lead_rate,
        "top_equipment": top_equipment,
    }

    generated_at = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")

    return render_template(
        "stats.html",
        stats=stats_data,
        volume_labels=volume_labels,
        volume_counts=volume_counts,
        generated_at=generated_at,
    ), 200, {"Cache-Control": "no-store"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8003, debug=True)

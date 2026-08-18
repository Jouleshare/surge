import base64
import os
import tempfile
from unittest.mock import patch

_TEST_RUNTIME = tempfile.mkdtemp(prefix="surge-test-")
os.environ.setdefault("ADMIN_USER", "test-admin")
os.environ.setdefault("ADMIN_PASS", "test-password")
os.environ.setdefault("SURGE_RUNTIME_DIR", _TEST_RUNTIME)

from surge_app import handle_message, conversation_state, app


FAKE_LOADOUT = {
    "baseline": {"cost_total": 12000, "co2_tonnes": 40, "fuel_liters": 1000},
    "ampd": {
        "cost_total": 9000,
        "co2_tonnes": 10,
        "unit_name": "Ampd 200",
        "unit_count": 1,
        "weekly_rate": 650,
        "hire_weeks": 12,
    },
    "recommended_bess": {"name": "Ampd 200"},
    "gen_kva": 200,
    "weeks": 12,
}


def fake_call_loadout(items, weeks, recharge_source="gen", region=None):
    data = {
        "baseline": {
            "cost_total": 1000 * weeks,
            "co2_tonnes": 2 * weeks,
            "fuel_liters": 100 * weeks,
        },
        "ampd": {
            "cost_total": (600 if recharge_source == "gen" else 500) * weeks,
            "co2_tonnes": 0.5 * weeks,
            "unit_name": "Ampd 200",
            "unit_count": 1,
            "weekly_rate": 600 if recharge_source == "gen" else 500,
            "hire_weeks": weeks,
        },
        "recommended_bess": {"name": "Ampd 200"},
        "gen_kva": max([i.get("kva") or 200 for i in items] or [200]),
        "weeks": weeks,
    }
    if any(i["name"].startswith("Tower Crane") and i.get("qty", 1) >= 2 for i in items):
        data["ampd"]["unit_name"] = "Ampd 400"
    return data


@patch("surge_app.call_loadout", side_effect=fake_call_loadout)
def run_smoke_tests(_mock_call_loadout):
    conversation_state.clear()

    first = handle_message("tower crane 500kva, 26 weeks, generator", "uk-flow")
    assert "*Recommendation:*" in first
    assert "Weekly cost" in first
    assert "Saves:" in first
    assert "Tower Crane — 500kVA" in first

    followup_weeks = handle_message("what about 52 weeks", "uk-flow")
    assert "52 weeks" in followup_weeks
    assert "Saves: *£20,800*" in followup_weeks

    compare = handle_message("compare mains", "uk-flow")
    assert "*Recharge comparison*" in compare
    assert "Ampd + mains recharge" in compare
    assert "Ampd + generator recharge" in compare

    add_cabin = handle_message("add a welfare cabin", "uk-flow")
    assert "Site Cabins (Small)" in add_cabin
    assert "52 weeks" in add_cabin

    two_cranes = handle_message("make it 2 cranes", "uk-flow")
    assert "Tower Crane x2 — 500kVA each" in two_cranes

    us_reply = handle_message("[US] tower crane 500kva, 26 weeks, mains", "15551234567")
    assert "$" in us_reply
    assert "mains charge" in us_reply

    canada_reply = handle_message("Toronto tower crane 500kva, 26 weeks, mains", "canada-flow")
    assert "C$" in canada_reply
    assert "Ampd team pick this up for Canada" in canada_reply

    canada_override = handle_message("[CA] tower crane 500kva, 26 weeks, generator", "override-flow")
    assert "C$" in canada_override

    spanish_reply = handle_message("2 grúas torre 160kVA durante 52 semanas con carga desde red", "spanish-flow")
    assert "*Recomendación:*" in spanish_reply
    assert "Coste semanal" in spanish_reply
    assert "Grúa torre x2 — 160kVA cada una" in spanish_reply
    assert "Charging assumptions" not in spanish_reply
    assert "Conversion" not in spanish_reply

    spanish_followup = handle_message("comparar generador", "spanish-flow")
    assert "*Comparación de recarga*" in spanish_followup
    assert "recarga con generador" in spanish_followup

    brand_cranes = handle_message(
        "104 weeks, 5x Wolffkran cranes: 6015 Clear, 7532 Cross, 630B, 700B, 1250B, Diesel generator",
        "brand-flow",
    )
    assert "Quick one" not in brand_cranes
    assert "Tower Crane" in brand_cranes
    assert "x5" in brand_cranes
    assert "104 weeks" in brand_cranes

    brandon_first = handle_message("X2 tower cranes 160 KVA", "brandon-flow")
    assert "how many" not in brandon_first.lower()
    assert "*Recommendation:*" in brandon_first
    assert "Screening basis" in brandon_first
    assert "I'd screen this" in brandon_first
    brandon_second = handle_message("52 weeks mains", "brandon-flow")
    assert "Quick one" not in brandon_second
    assert "Tower Crane x2 — 160kVA each" in brandon_second
    assert "52 weeks" in brandon_second

    qty_first = handle_message("tower cranes 160 kva, 52 weeks mains", "bare-qty-flow")
    assert "how many" in qty_first.lower()
    qty_second = handle_message("2", "bare-qty-flow")
    assert "Quick one" not in qty_second
    assert "Tower Crane x2 — 160kVA each" in qty_second
    assert "Tower Crane — 160kVA" not in qty_second
    assert "52 weeks" in qty_second

    conversation_state.clear()
    guided_first = handle_message("tower cranes", "guided-flow")
    assert "how many" in guided_first.lower()
    guided_second = handle_message("2", "guided-flow")
    assert "160kva" in guided_second.lower() or "medium" in guided_second.lower()
    guided_third = handle_message("160kva", "guided-flow")
    assert "*Recommendation:*" in guided_third
    assert "Screening basis" in guided_third
    guided_fourth = handle_message("52 weeks mains", "guided-flow")
    assert "Tower Crane x2 — 160kVA each" in guided_fourth
    assert "52 weeks" in guided_fourth

    conversation_state.clear()
    guided_kva_space = [
        handle_message("Tower cranes", "guided-kva-space"),
        handle_message("3 tower cranes", "guided-kva-space"),
        handle_message("200 KVA", "guided-kva-space"),
        handle_message("52 weeks mains", "guided-kva-space"),
    ]
    assert "how many" in guided_kva_space[0].lower()
    assert "load per crane" in guided_kva_space[1].lower()
    assert "*Recommendation:*" in guided_kva_space[2]
    assert "Screening basis" in guided_kva_space[2]
    assert "Tower Crane x3 — 200kVA each" in guided_kva_space[3]

    conversation_state.clear()
    guided_kva_tight = [
        handle_message("Tower cranes", "guided-kva-tight"),
        handle_message("3", "guided-kva-tight"),
        handle_message("200kva", "guided-kva-tight"),
        handle_message("52 weeks mains", "guided-kva-tight"),
    ]
    assert "Tower Crane x3 — 200kVA each" in guided_kva_tight[3]

    jobs_reply = handle_message("JOBS", "uk-flow")
    assert "Saved Surge jobs" in jobs_reply
    assert "S-" in jobs_reply
    assert "job_" not in jobs_reply

    learn_reply = handle_message("LEARN: correct, Brandon says this assumption is approved for rollout", "uk-flow")
    assert "Saved learning feedback" in learn_reply
    assert "correct" in learn_reply
    assert "against S-" in learn_reply

    client = app.test_client()
    credentials = base64.b64encode(b"test-admin:test-password").decode()
    jobs_api = client.get("/jobs?format=json", headers={"Authorization": f"Basic {credentials}"})
    assert jobs_api.status_code == 200
    assert jobs_api.get_json()["count"] >= 1

    artifacts_api = client.get("/artifacts?format=json", headers={"Authorization": f"Basic {credentials}"})
    assert artifacts_api.status_code == 200
    assert "artifacts" in artifacts_api.get_json()

    help_reply = handle_message("hello", "uk-help")
    assert "site power advisor" in help_reply
    assert "i'll guide the rest" in help_reply.lower()

    contact_prompt = handle_message("CONTACT", "uk-contact")
    assert "name plus email or mobile" in contact_prompt
    contact_saved = handle_message("Jane, jane@example.com", "uk-contact")
    assert "I've passed your details" in contact_saved

    print("Smoke tests passed")


if __name__ == "__main__":
    run_smoke_tests()

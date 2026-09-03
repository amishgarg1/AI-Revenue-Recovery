"""
API tests.

The logic underneath is covered elsewhere; what these check is the layer a
judge and the dashboard actually touch. Two things matter most:

* `/api/llm/validate` behaves exactly as the validator page claims. That page
  is the only place the project's one architectural claim — the LLM never
  touches a rupee — is demonstrated rather than asserted, and it will be on
  screen during the pitch. If a sample labelled "reject" ever starts passing,
  the demo says the opposite of what it means to.
* `/api/audit/tamper` genuinely breaks the chain and `/api/audit/verify`
  genuinely catches it. An integrity feature nobody tests is a claim.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import ledger
from app.core.orchestrator import Orchestrator
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Action, Case, Customer, Invoice, Order, Payment
from app.sim.generator import generate_dataset

# Enough to exercise every lane without paying for the full 815-case batch.
SAMPLE_ORDERS = 70
SAMPLE_INVOICES = 25


@pytest.fixture(scope="module")
def client():
    """A batch-completed database behind a real TestClient."""
    from app.core.detector import detector

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ledger.reset_head_cache()
    detector.reset()

    data = generate_dataset(seed=42)
    order_owner = {o["order_id"]: o["customer_id"] for o in data["orders"]}
    invoice_owner = {i["invoice_id"]: i["customer_id"] for i in data["invoices"]}
    for case in data["cases"]:
        case["customer_id"] = (
            order_owner.get(case["entity_id"]) if case["entity_type"] == "order"
            else invoice_owner.get(case["entity_id"])
        )

    kept = (
        [c for c in data["cases"] if c["entity_type"] == "invoice"][:SAMPLE_INVOICES]
        + [c for c in data["cases"] if c["entity_type"] == "order"][:SAMPLE_ORDERS]
    )

    db = SessionLocal()
    db.bulk_insert_mappings(Customer, data["customers"])
    db.bulk_insert_mappings(Order, data["orders"])
    db.bulk_insert_mappings(Payment, data["payments"])
    db.bulk_insert_mappings(Invoice, data["invoices"])
    db.bulk_insert_mappings(Case, kept)
    db.commit()

    Orchestrator(db, real_link_budget=0).run()
    db.close()

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
    ledger.reset_head_cache()


# --------------------------------------------------------------- hermeticity

def test_the_suite_cannot_reach_a_provider():
    """
    The tests must behave identically with keys configured and without them.

    Unsetting the keys is not enough — importing litellm calls `load_dotenv()`
    and restores them — so the guard is an explicit flag checked at call time.
    This asserts the behaviour rather than the environment: with real keys in
    .env, the client must still return a deterministic template and the link
    builder must still refuse to mint.
    """
    from app.llm.client import get_message_template
    from app.razorpay_client.links import has_credentials

    template = get_message_template("NUDGE_CUSTOMER", 1, "whatsapp", "en")
    assert not template["llm_used"]
    assert template["llm_rejected_reason"] == "OFFLINE"
    assert not has_credentials()


# ------------------------------------------------------- the validator page

def test_every_sample_is_labelled_with_what_it_actually_does(client):
    """
    The samples on the validator page each carry an `expect` label, and the
    page shows a green or amber dot from it. If the label and the validator
    ever disagree, the page confidently misreports the guardrail.
    """
    samples = client.get("/api/llm/samples").json()["samples"]
    assert len(samples) >= 8

    for sample in samples:
        result = client.post("/api/llm/validate", json={
            "body": sample["body"],
            "channel": sample["channel"],
            "language": sample["language"],
        }).json()
        assert result["ok"] == (sample["expect"] == "pass"), (
            f"{sample['id']} is labelled {sample['expect']} but the validator "
            f"returned ok={result['ok']} ({result['reason']})"
        )


@pytest.mark.parametrize("sample_id,reason_prefix", [
    ("wrote_the_amount", "LLM_WROTE_A_NUMBER"),
    ("wrote_a_date", "LLM_WROTE_A_NUMBER"),
    ("dropped_the_link", "MISSING_TOKEN"),
    ("legal_threat", "BANNED_PHRASE"),
    ("hinglish_threat", "BANNED_PHRASE"),
    ("sms_too_long", "TOO_LONG"),
    ("voice_no_optout", "MISSING_AUTOMATED_CALL_DISCLOSURE"),
])
def test_each_rejection_gives_the_reason_the_page_shows(client, sample_id,
                                                        reason_prefix):
    samples = {s["id"]: s for s in client.get("/api/llm/samples").json()["samples"]}
    sample = samples[sample_id]
    result = client.post("/api/llm/validate", json={
        "body": sample["body"],
        "channel": sample["channel"],
        "language": sample["language"],
    }).json()

    assert not result["ok"]
    assert result["reason"].startswith(reason_prefix)


def test_a_rejected_draft_still_produces_a_sendable_message(client):
    """
    The point of the fallback: a rejection is a downgrade, not an outage. The
    page says so, so it had better be true.
    """
    samples = {s["id"]: s for s in client.get("/api/llm/samples").json()["samples"]}
    sample = samples["wrote_the_amount"]
    result = client.post("/api/llm/validate", json={
        "body": sample["body"],
        "channel": sample["channel"],
        "language": sample["language"],
    }).json()

    assert result["used"] == "deterministic_fallback"
    assert result["would_send"]
    assert "{{" not in result["would_send"]
    assert "1,499" not in result["would_send"]

    # And the number in it is the database's, not the model's guess of 1,499.
    # Asserted against the case the endpoint says it read, because the amount
    # used to be a constant in the endpoint that matched no case at all.
    case = client.get(f"/api/cases/{result['values_from_case']}").json()["case"]
    expected = f"{case['amount_at_risk_paise'] / 100:,.2f}"
    assert expected in result["would_send"]


def test_an_accepted_draft_renders_the_model_template(client):
    samples = {s["id"]: s for s in client.get("/api/llm/samples").json()["samples"]}
    result = client.post("/api/llm/validate", json={
        "body": samples["clean"]["body"],
        "channel": "whatsapp",
        "language": "en",
    }).json()

    assert result["ok"]
    assert result["used"] == "llm_template"
    assert "{{" not in result["would_send"]


def test_the_hindi_banned_list_is_actually_wired_up(client):
    """An English-only list would pass a Hinglish legal threat."""
    banned = client.get("/api/llm/samples").json()["banned_phrases"]
    assert "kanooni" in banned
    assert "adalat" in banned


# ------------------------------------------------------------ audit ledger

def test_verify_reports_a_clean_chain_after_a_run(client):
    result = client.get("/api/audit/verify").json()
    assert result["valid"]
    assert result["records"] > 0
    assert result["broken_at"] == []


def test_tampering_is_detected_named_and_reversible(client):
    """
    Tamper, catch it, put the row back, and watch the chain go valid again.

    The round trip matters for two reasons. It proves detection is derived
    from content rather than from some "edited" flag — restoring the original
    payload restores the hash. And it leaves the ledger clean, so this test
    does not quietly depend on running after every other one.
    """
    from app.models import Event

    assert client.get("/api/audit/verify").json()["valid"]

    tampered = client.post("/api/audit/tamper").json()
    assert tampered["status"] == "tampered"
    assert tampered["before"] != tampered["after"]

    caught = client.get("/api/audit/verify").json()
    assert not caught["valid"]
    assert caught["first_break"] == tampered["event_id"]

    db = SessionLocal()
    try:
        row = db.query(Event).filter(Event.event_id == tampered["event_id"]).one()
        row.payload_json = tampered["before"]
        db.commit()
    finally:
        db.close()

    assert client.get("/api/audit/verify").json()["valid"]


def test_the_restore_endpoint_closes_the_loop(client):
    """
    Tamper is a one-way door without this.

    On the dashboard the ledger would read BROKEN on every visit from then on,
    and the committed database would have to be restored from git — so the
    demonstration could be given exactly once.
    """
    assert client.get("/api/audit/verify").json()["valid"]

    tampered = client.post("/api/audit/tamper").json()
    assert not client.get("/api/audit/verify").json()["valid"]

    restored = client.post("/api/audit/restore").json()
    assert restored["status"] == "restored"
    assert tampered["event_id"] in restored["restored"]
    # Restoring the bytes restores the hash: detection is derived from content,
    # not from a flag saying the row was edited.
    assert restored["chain"]["valid"]
    assert client.get("/api/audit/verify").json()["valid"]


def test_restoring_a_clean_ledger_is_not_an_error(client):
    """The button can be clicked twice; the second click is a no-op."""
    assert client.get("/api/audit/verify").json()["valid"]

    result = client.post("/api/audit/restore").json()
    assert result["status"] == "nothing_to_restore"
    assert result["restored"] == []
    assert result["chain"]["valid"]


def test_tampering_twice_still_restores(client):
    """
    The second tamper must not record the already-tampered payload as the
    original, or restore would put the tampered value back and call it clean.
    """
    original = client.post("/api/audit/tamper").json()["before"]
    client.post("/api/audit/tamper")

    assert client.post("/api/audit/restore").json()["chain"]["valid"]

    from app.models import Event
    db = SessionLocal()
    try:
        row = db.query(Event).filter(Event.action == "OUTCOME").first()
        assert row.payload_json == original
    finally:
        db.close()


# ------------------------------------------------------------------ metrics

def test_health_reports_which_integrations_are_configured(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["data"]["cases"] > 0
    # The keys must exist even when nothing is configured — the sidebar reads
    # them to say "fallback" rather than silently implying "live".
    for key in ("razorpay_test_mode", "llm", "voice_tts"):
        assert key in body["integrations"]


def test_summary_never_credits_the_control_arm_to_the_agent(client):
    e = client.get("/api/metrics/summary").json()
    assert e["treatment_n"] > 0 and e["control_n"] > 0
    assert e["net_lift"] == pytest.approx(
        e["treatment_rate"] - e["control_rate"], abs=1e-9
    )
    assert e["ci_lower"] <= e["net_lift"] <= e["ci_upper"]


def test_guardrails_lists_all_eleven_gates_including_silent_ones(client):
    body = client.get("/api/metrics/guardrails").json()
    gates = {g["gate"] for g in body["gates"]}
    assert gates == {f"G{i:02d}" for i in range(1, 12)}


def test_the_timeline_covers_the_whole_horizon(client):
    body = client.get("/api/metrics/timeline").json()
    assert len(body["rows"]) == body["ticks"]
    assert any(r["quiet"] for r in body["rows"]), "no quiet-hours ticks"
    assert any(not r["quiet"] for r in body["rows"]), "every tick is quiet"

    # Cumulative series must never go backwards.
    for key in ("cum_treatment", "cum_control"):
        series = [r[key] for r in body["rows"]]
        assert series == sorted(series), f"{key} decreases"


def test_exceptions_explain_every_unrecovered_case(client):
    rows = client.get("/api/metrics/exceptions").json()["exceptions"]
    assert rows
    assert all(r["reason"] and r["count"] > 0 for r in rows)
    # Ranked by money left on the table, which is the order the page shows.
    amounts = [r["amount_paise"] for r in rows]
    assert amounts == sorted(amounts, reverse=True)


def test_flow_totals_match_the_sum_of_its_classes(client):
    body = client.get("/api/metrics/flow").json()
    assert body["at_risk_paise"] == sum(
        c["at_risk_paise"] for c in body["by_class"]
    )
    assert body["recovered_paise"] == sum(
        c["recovered_paise"] for c in body["by_class"]
    )


# -------------------------------------------------------------------- cases

def test_case_list_filters_narrow_the_result(client):
    everything = client.get("/api/cases", params={"limit": 500}).json()
    recovered = client.get(
        "/api/cases", params={"state": "RECOVERED", "limit": 500}
    ).json()

    assert recovered["total"] < everything["total"]
    assert all(c["state"] == "RECOVERED" for c in recovered["cases"])


def test_case_list_is_ordered_by_money_at_risk(client):
    rows = client.get("/api/cases", params={"limit": 50}).json()["cases"]
    amounts = [c["amount_at_risk_paise"] for c in rows]
    assert amounts == sorted(amounts, reverse=True)


def test_case_detail_carries_the_whole_decision_trail(client):
    case_id = client.get("/api/cases", params={"limit": 1}).json()["cases"][0]["case_id"]
    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["case"]["case_id"] == case_id
    assert detail["events"], "a case with no ledger events is unauditable"
    for action in detail["actions"]:
        assert len(action["gate_decisions_json"]) == 11


def test_an_unknown_case_is_a_404_not_a_500(client):
    assert client.get("/api/cases/case_does_not_exist").status_code == 404

"""
Reading somebody else's export, and planning against it.

Three claims are being tested. That a real file - their column names, their
amount formats, their bad rows - is read correctly and that every rejection
says which line and why. That the plan uses the same decision path as the
batch. And that nothing from the file is stored, because a payment export is
customer data.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.ingest.plan import build_plan, planning_hour
from app.ingest.reader import IngestError, map_columns, read_csv
from app.main import app

CLEAN = """Order ID,Customer ID,Amount (INR),Failure Reason,Error Source,Error Step,Bank
ord_1,cust_1,"10,000.00",card_declined_by_issuer,bank,authorization,HDFC
ord_2,cust_2,450.50,issuer_down,bank,authorization,ICICI
ord_3,cust_3,"1,20,000.00",payment_blocked_by_risk,business,authorization,SBI
"""


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def upload(client, text: str, name: str = "export.csv", **params):
    return client.post(
        "/api/ingest/plan",
        files={"file": (name, io.BytesIO(text.encode()), "text/csv")},
        params=params,
    )


# --------------------------------------------------------- their column names

def test_a_real_export_maps_without_being_told():
    """Nobody's export happens to use our field names."""
    mapping = map_columns(["Order ID", "Customer ID", "Amount (INR)",
                           "Failure Reason", "Error Source", "Bank"])

    assert mapping["entity_id"] == "Order ID"
    assert mapping["amount_paise"] == "Amount (INR)"
    assert mapping["customer_id"] == "Customer ID"
    assert mapping["error_reason"] == "Failure Reason"
    assert mapping["issuer"] == "Bank"


def test_a_header_is_claimed_by_only_one_field():
    """
    An export with both `order_id` and `id` must not have the vaguer column
    silently override the specific one.
    """
    mapping = map_columns(["order_id", "id", "amount_paise"])
    assert mapping["entity_id"] == "order_id"


def test_a_paise_column_is_not_divided_by_a_hundred():
    """
    The hundredfold error. An export naming paise is trusted as paise even
    though `amount` alone is ambiguous.
    """
    read = read_csv("order_id,amount_paise,reason\nord_1,150000,card_expired\n")
    assert read.amount_unit == "paise"
    assert read.rows[0]["amount_at_risk_paise"] == 150_000


def test_a_rupee_column_is_converted():
    read = read_csv("order_id,Amount (INR),reason\nord_1,1500.00,card_expired\n")
    assert read.amount_unit == "rupees"
    assert read.rows[0]["amount_at_risk_paise"] == 150_000


def test_indian_digit_grouping_survives():
    """A spreadsheet writes 1,20,000.00 and a naive float() throws."""
    read = read_csv('order_id,Amount (INR),reason\nord_1,"1,20,000.00",x\n')
    assert read.rows[0]["amount_at_risk_paise"] == 120_000_00


def test_a_currency_symbol_survives():
    read = read_csv("order_id,Amount (INR),reason\nord_1,₹2500.00,x\n")
    assert read.rows[0]["amount_at_risk_paise"] == 250_000


def test_an_excel_byte_order_mark_does_not_break_the_first_column():
    """
    Left in place the BOM makes the first header unmatchable and every row
    fails for a missing id - a baffling error to debug from the message.
    """
    read = read_csv("﻿Order ID,Amount (INR),reason\nord_1,100.00,x\n")
    assert len(read.rows) == 1


# ----------------------------------------------------------- their bad rows

def test_every_rejected_row_names_its_line_and_the_reason():
    """
    "17 rows were invalid" is useless to somebody with a 40,000-line export.
    """
    read = read_csv(
        "Order ID,Amount (INR),reason\n"
        "ord_1,100.00,card_expired\n"
        ",cust,card_expired\n"                 # line 3: no id
        "ord_3,N/A,card_expired\n"             # line 4: unparseable
        "ord_4,-500.00,refund_issued\n"        # line 5: nothing at risk
    )

    assert len(read.rows) == 1
    assert [p.line for p in read.problems] == [3, 4, 5]
    assert "no id" in read.problems[0].problem
    assert "not a number" in read.problems[1].problem
    assert "nothing at risk" in read.problems[2].problem


def test_parsing_continues_past_a_bad_row():
    """A report of all forty problems beats forty runs."""
    read = read_csv(
        "Order ID,Amount (INR),reason\n"
        ",x,y\nord_2,100.00,card_expired\n,x,y\nord_4,200.00,card_expired\n")
    assert len(read.rows) == 2
    assert len(read.problems) == 2


def test_a_missing_required_column_says_what_was_found():
    """The error has to be actionable without reading our source."""
    with pytest.raises(IngestError) as e:
        read_csv("Reference,Reason\nabc,card_expired\n")

    message = str(e.value)
    assert "amount_paise" in message
    assert "Reference" in message      # the headers that were there
    assert "amount" in message         # and what we would have accepted


def test_an_empty_file_is_rejected_clearly():
    with pytest.raises(IngestError, match="empty"):
        read_csv("   \n")


def test_a_file_of_only_bad_rows_is_rejected_with_the_first_reason():
    with pytest.raises(IngestError, match="line 2"):
        read_csv("Order ID,Amount (INR)\n,100.00\n,200.00\n")


def test_the_row_cap_reports_itself_rather_than_truncating_silently():
    body = "Order ID,Amount (INR)\n" + "".join(
        f"ord_{i},100.00\n" for i in range(10))
    read = read_csv(body, max_rows=4)

    assert len(read.rows) == 4
    assert any("stopped after" in p.problem for p in read.problems)


# ------------------------------------------------ the same decision path

def test_the_plan_routes_the_way_the_classifier_does():
    read = read_csv(CLEAN)
    plan = build_plan(read.rows)

    classes = {r["recovery_class"]: r["cases"] for r in plan["by_class"]}
    assert classes["SWITCH_METHOD"] == 1        # card declined by issuer
    assert classes["MANUAL_REVIEW"] == 1        # risk block
    assert classes["AUTO_RETRY"] == 1           # issuer down


def test_the_plan_adds_up():
    """Internal consistency: every case is either contacted or not."""
    read = read_csv(CLEAN)
    plan = build_plan(read.rows)

    assert plan["cases"] == plan["would_contact"] + plan["would_not_contact"]
    assert plan["cases"] == len(read.rows)
    assert plan["amount_at_risk_paise"] == sum(
        r["amount_at_risk_paise"] for r in read.rows)


def test_planned_spend_matches_the_channels_it_would_use():
    """The figure a merchant will check first."""
    from app.core.ladder import tier_cost

    read = read_csv(CLEAN)
    plan = build_plan(read.rows)

    channel_tier = {"silent": 0, "whatsapp": 1, "sms": 2, "voice": 3, "human": 4}
    expected = sum(
        tier_cost(channel_tier[row["channel"]]) * row["messages"]
        for row in plan["by_channel"]
    )
    assert plan["planned_spend_paise"] == expected


def test_a_merchant_policy_changes_the_plan():
    """The same backlog, planned under different rules."""
    small = "Order ID,Amount (INR),reason\nord_1,250.00,card_declined_by_issuer\n"
    read = read_csv(small)

    default = build_plan(read.rows)
    uk = build_plan(read.rows, merchant_id="merchant_uk_subs")

    assert default["would_contact"] == 1
    assert uk["would_contact"] == 0
    assert uk["refusals"][0]["gate"] == "G06"


@pytest.mark.parametrize("merchant", [None, "merchant_uk_subs",
                                      "merchant_marketplace"])
def test_the_plan_is_never_refused_on_timing(merchant):
    """
    Uploading at midnight must not refuse everything on quiet hours and tell
    the merchant nothing about their backlog - and the hour has to come from
    *their* window. A fixed 11:00 IST sits inside the quiet hours of a merchant
    in another timezone, whose plan then came back entirely blocked on G02.
    """
    from app.core import config
    from app.core.policy import _in_quiet_window

    plan = build_plan(read_csv(CLEAN).rows, merchant_id=merchant)
    policy = config.active(merchant)

    assert not _in_quiet_window(plan["evaluated_at_ist_hour"], policy)
    assert not any(r["gate"] == "G02" for r in plan["refusals"])


def test_the_planning_hour_is_inside_the_voice_window_too():
    """
    Voice is the narrowest window. Choosing its midpoint means a voice rung is
    not refused for timing either.
    """
    from app.core import config

    for merchant in (None, "merchant_uk_subs"):
        p = config.active(merchant)
        assert p.voice_start_ist <= planning_hour(p) < p.voice_end_ist


# -------------------------------------------------------------- the honesty

def test_recovery_is_reported_as_a_range_not_a_number():
    """
    A single confident figure on somebody else's data would be the most
    dishonest thing this project could print.
    """
    plan = build_plan(read_csv(CLEAN).rows)
    p = plan["projection"]

    assert p["low_paise"] < p["at_our_assumptions_paise"] < p["high_paise"]
    assert "projection, not a measurement" in p["basis"]


def test_the_plan_states_what_it_assumed():
    plan = build_plan(read_csv(CLEAN).rows)
    joined = " ".join(plan["assumptions"]).lower()

    assert "consent" in joined            # assumed present, and says so
    assert "first touch" in joined        # day one, not the whole ladder


# ------------------------------------------------------------- the endpoint

def test_the_endpoint_returns_a_plan(client):
    body = upload(client, CLEAN).json()

    assert body["rows_usable"] == 3
    assert body["plan"]["cases"] == 3
    assert body["mapping"]["amount_paise"] == "Amount (INR)"


def test_nothing_from_the_upload_is_stored(client):
    """
    A payment export is customer data. The response carries counts and money,
    never a row, and the database must be untouched.
    """
    from app.db import SessionLocal
    from app.models import Case

    db = SessionLocal()
    try:
        before = db.query(Case).count()
    finally:
        db.close()

    body = upload(client, CLEAN).json()

    db = SessionLocal()
    try:
        assert db.query(Case).count() == before
    finally:
        db.close()

    assert body["stored"] is False
    # No identifier from the file may appear anywhere in the response.
    assert "ord_1" not in str(body["plan"])
    assert "cust_1" not in str(body["plan"])


def test_an_unreadable_file_is_a_422_with_a_useful_message(client):
    response = upload(client, "Reference,Reason\nabc,card_expired\n")

    assert response.status_code == 422
    assert "amount_paise" in response.json()["detail"]


def test_a_non_utf8_file_is_a_400(client):
    response = client.post(
        "/api/ingest/plan",
        files={"file": ("x.csv", io.BytesIO(b"\xff\xfeOrder\x00"), "text/csv")},
    )
    assert response.status_code == 400
    assert "UTF-8" in response.json()["detail"]


def test_rejected_rows_come_back_with_line_numbers(client):
    body = upload(client, CLEAN + ",bad,row\n").json()

    assert body["rows_rejected"] == 1
    assert body["problems"][0]["line"] == 5

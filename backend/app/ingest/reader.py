"""
Reading somebody else's CSV.

The fair question a merchant asks is "what would this do on *our* data", and
until now there was no way to answer it: every case came from
`generate_dataset(seed=42)`. This module takes a file of real failed payments
and turns it into the facts the classifier reads.

Three things it has to get right, in order of how badly they bite:

**Nothing is stored.** A merchant's payment export is customer data - emails,
phone numbers, names. It is parsed in memory, planned against, and dropped.
Nothing reaches the database, so there is no retention question to answer and
no breach surface to defend. The plan that comes back carries counts and
money, never a row.

**A rejected row says why, and which one.** "17 rows were invalid" is useless
to somebody with a 40,000-line export. Every rejection names its line and what
was wrong with it, and parsing continues rather than stopping at the first
one - a report of all forty problems beats forty runs.

**Column names are theirs, not ours.** Nobody's export happens to use our
field names. Common aliases are accepted, mapping is reported back so a
merchant can see what was matched to what, and an unmatched required column is
an error naming the headers that *were* found.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# What a row must carry for a decision to be possible at all. Everything else
# improves the answer; these make it exist.
REQUIRED = ("entity_id", "amount_paise")

# Header aliases, lowercased and stripped of non-letters before matching, so
# "Order ID", "order_id" and "ORDER-ID" are the same column.
ALIASES: Dict[str, tuple] = {
    "entity_id": ("orderid", "order", "id", "entityid", "invoiceid",
                  "paymentid", "referenceid", "txnid", "transactionid"),
    # Paise-named columns first, then rupee-named, then the ambiguous ones.
    # Order matters: an export carrying both `amount` and `amount_paise` means
    # the second, and matching the vaguer name first would divide by a hundred.
    "amount_paise": ("amountpaise", "amountinpaise",
                     "amountinr", "amountrupees", "amountinrupees", "inr",
                     "amount", "value", "amountdue", "outstanding",
                     "totalamount", "amountat risk", "amountatrisk"),
    "customer_id": ("customerid", "customer", "custid", "payerid", "userid"),
    "error_reason": ("errorreason", "reason", "failurereason", "error",
                     "declinereason"),
    "error_code": ("errorcode", "code", "failurecode"),
    "error_source": ("errorsource", "source"),
    "error_step": ("errorstep", "step"),
    "method": ("method", "paymentmethod", "instrument"),
    "issuer": ("bank", "issuer", "issuingbank", "wallet"),
    "entity_type": ("entitytype", "type", "recordtype"),
    "entity_status": ("status", "entitystatus", "orderstatus", "state"),
    "days_overdue": ("daysoverdue", "overduedays", "agedays", "age"),
    "attempt_no": ("attemptno", "attempt", "attempts", "retrycount"),
}

# Amounts arrive in rupees about as often as in paise, and getting it wrong is
# a hundredfold error in the headline. A column named for paise is trusted; a
# column named for rupees is converted; anything ambiguous is decided by the
# heuristic in `_amount_paise` and reported.
PAISE_HEADERS = ("amountpaise", "amountinpaise")
RUPEE_HEADERS = ("amountrupees", "amountinr", "amountinrupees", "inr")


@dataclass
class RowProblem:
    line: int
    column: Optional[str]
    problem: str


@dataclass
class ReadResult:
    rows: List[dict] = field(default_factory=list)
    problems: List[RowProblem] = field(default_factory=list)
    mapping: Dict[str, str] = field(default_factory=dict)
    unmapped_headers: List[str] = field(default_factory=list)
    amount_unit: str = "paise"
    total_lines: int = 0


class IngestError(ValueError):
    """The file cannot be read at all. Distinct from a row being unusable."""


def _normalise(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").lower())


def map_columns(headers: List[str]) -> Dict[str, str]:
    """
    Match the file's headers to our fields.

    First match wins, and a header is claimed by at most one field, so an
    export with both `order_id` and `id` does not have `id` silently override
    the more specific column.
    """
    normalised = {h: _normalise(h) for h in headers if h}
    mapping: Dict[str, str] = {}
    claimed = set()

    for field_name, aliases in ALIASES.items():
        for alias in aliases:
            for header, norm in normalised.items():
                if norm == alias and header not in claimed:
                    mapping[field_name] = header
                    claimed.add(header)
                    break
            if field_name in mapping:
                break

    return mapping


def _amount_paise(raw: str, unit: str) -> Optional[int]:
    """
    Parse an amount, in whatever shape a spreadsheet exported it.

    Handles thousands separators, a currency symbol, and a trailing minus.
    Returns None when it is not a number at all - the caller reports the line
    rather than guessing.
    """
    text = (raw or "").strip()
    if not text:
        return None

    text = re.sub(r"[₹$,\s]", "", text)
    negative = text.startswith("-") or text.endswith("-")
    text = text.strip("-")
    if not text:
        return None

    try:
        value = float(text)
    except ValueError:
        return None

    if negative:
        value = -value

    if unit == "rupees":
        return int(round(value * 100))
    if unit == "paise":
        return int(round(value))

    # Ambiguous column. A value with decimal places is rupees - nobody exports
    # fractional paise - and a whole number is taken at face value as paise.
    return int(round(value * 100)) if "." in raw else int(round(value))


def _amount_unit(header: Optional[str]) -> str:
    norm = _normalise(header or "")
    if norm in PAISE_HEADERS:
        return "paise"
    if norm in RUPEE_HEADERS:
        return "rupees"
    return "ambiguous"


def _int(raw: str) -> Optional[int]:
    try:
        return int(float((raw or "").strip()))
    except (TypeError, ValueError):
        return None


def read_csv(text: str, *, max_rows: int = 50_000) -> ReadResult:
    """
    Parse a CSV export into rows the classifier can read.

    `max_rows` is a guard rather than a limit anyone should hit: the plan is
    computed synchronously, and an unbounded upload would hold a request open
    for minutes.
    """
    if not text.strip():
        raise IngestError("The file is empty")

    # Excel writes a BOM. Left in place it makes the first header unmatchable
    # and every row fail for a missing id, which is a baffling error to debug.
    if text.startswith("﻿"):
        text = text[1:]

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("The file has no header row")

    mapping = map_columns(list(reader.fieldnames))
    missing = [f for f in REQUIRED if f not in mapping]
    if missing:
        raise IngestError(
            f"Could not find a column for {', '.join(missing)}. "
            f"Headers found: {', '.join(reader.fieldnames)}. "
            f"Accepted names for {missing[0]}: "
            f"{', '.join(ALIASES[missing[0]][:5])}"
        )

    result = ReadResult(
        mapping=mapping,
        unmapped_headers=[h for h in reader.fieldnames
                          if h and h not in mapping.values()],
        amount_unit=_amount_unit(mapping.get("amount_paise")),
    )

    for line, raw in enumerate(reader, start=2):   # line 1 is the header
        result.total_lines += 1
        if result.total_lines > max_rows:
            result.problems.append(RowProblem(
                line, None,
                f"stopped after {max_rows:,} rows; split the file and re-run"))
            break

        def value(name):
            column = mapping.get(name)
            return (raw.get(column) or "").strip() if column else ""

        entity_id = value("entity_id")
        if not entity_id:
            result.problems.append(RowProblem(line, mapping["entity_id"],
                                              "no id"))
            continue

        amount = _amount_paise(value("amount_paise"), result.amount_unit)
        if amount is None:
            result.problems.append(RowProblem(
                line, mapping["amount_paise"],
                f"amount {value('amount_paise')!r} is not a number"))
            continue
        if amount <= 0:
            # A refund or a zero-value row is not a recovery case. Reported
            # rather than dropped, so the counts add up.
            result.problems.append(RowProblem(
                line, mapping["amount_paise"],
                f"amount is {amount} paise; nothing at risk"))
            continue

        entity_type = (value("entity_type") or "order").lower()
        if entity_type not in ("order", "invoice"):
            entity_type = "invoice" if "invoice" in entity_type else "order"

        result.rows.append({
            "line": line,
            "entity_id": entity_id,
            "customer_id": value("customer_id") or entity_id,
            "entity_type": entity_type,
            "entity_status": value("entity_status") or None,
            "amount_at_risk_paise": amount,
            "days_overdue": _int(value("days_overdue")),
            "payment": {
                "attempt_no": _int(value("attempt_no")) or 1,
                "method": value("method") or None,
                "issuer": value("issuer") or None,
                "amount_paise": amount,
                "error_code": value("error_code") or None,
                "error_source": value("error_source") or None,
                "error_step": value("error_step") or None,
                "error_reason": value("error_reason") or None,
            },
        })

    if not result.rows:
        raise IngestError(
            f"No usable rows. {len(result.problems)} were rejected; the first "
            f"was line {result.problems[0].line}: {result.problems[0].problem}"
            if result.problems else "No usable rows and no problems recorded"
        )

    return result

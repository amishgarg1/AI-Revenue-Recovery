"""
Point the policy at a CSV of failed payments and print what it would do.

    python backend/scripts/plan.py examples/failed_payments.csv
    python backend/scripts/plan.py yours.csv --merchant merchant_uk_subs
    python backend/scripts/plan.py yours.csv --json

Nothing is stored. The file is parsed in memory, planned against, and dropped -
a payment export is customer data, and the plan that comes back carries counts
and money rather than rows.
"""

import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingest.plan import build_plan                      # noqa: E402
from app.ingest.reader import IngestError, read_csv         # noqa: E402


def rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", help="a CSV export of failed payments")
    parser.add_argument("--merchant", help="plan under this merchant's policy")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--problems", type=int, default=5,
                        help="how many rejected rows to list")
    args = parser.parse_args()

    with open(args.csv, encoding="utf-8-sig") as fh:
        text = fh.read()

    try:
        read = read_csv(text)
    except IngestError as e:
        print(f"Could not read {args.csv}:\n  {e}")
        return 1

    plan = build_plan(read.rows, merchant_id=args.merchant)

    if args.as_json:
        print(json.dumps({"mapping": read.mapping, "plan": plan},
                         indent=2, default=str))
        return 0

    print(f"{args.csv}")
    print(f"  {read.total_lines:,} rows read, {len(read.rows):,} usable, "
          f"{len(read.problems)} rejected")
    print(f"  amount column read as {read.amount_unit}")
    print()

    print("  COLUMNS MATCHED")
    for field, header in read.mapping.items():
        print(f"    {field:<22} <- {header}")
    if read.unmapped_headers:
        print(f"    (ignored: {', '.join(read.unmapped_headers)})")
    print()

    if read.problems:
        print("  ROWS REJECTED")
        for p in read.problems[:args.problems]:
            print(f"    line {p.line}: {p.problem}")
        if len(read.problems) > args.problems:
            print(f"    ... and {len(read.problems) - args.problems} more")
        print()

    print("  WHAT THE POLICY WOULD DO")
    print(f"    at risk            {rupees(plan['amount_at_risk_paise'])}")
    print(f"    would contact      {plan['would_contact']:,} of {plan['cases']:,}")
    print(f"    would not          {plan['would_not_contact']:,} "
          f"({plan['no_action_possible']:,} have no useful action at all)")
    print(f"    day-one spend      {rupees(plan['planned_spend_paise'])}")
    print(f"    policy             {plan['policy']}")
    print()

    print("  ROUTED AS")
    for row in plan["by_class"]:
        print(f"    {row['recovery_class']:<20} {row['cases']:>5}")
    print()

    print("  WOULD SEND")
    for row in plan["by_channel"]:
        print(f"    {row['channel']:<20} {row['messages']:>5}")
    print()

    if plan["refusals"]:
        print("  REFUSED BY")
        for row in plan["refusals"]:
            reasons = ", ".join(f"{k} x{v}" for k, v in row["reasons"].items())
            print(f"    {row['gate']}  {row['blocks']:>5}   {reasons}")
        print()

    p = plan["projection"]
    print("  PROJECTED INCREMENTAL RECOVERY")
    print(f"    {rupees(p['low_paise'])} to {rupees(p['high_paise'])}")
    print(f"    (at our assumptions: {rupees(p['at_our_assumptions_paise'])})")
    print()
    for line in [p["basis"]] + plan["assumptions"]:
        print(f"    - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

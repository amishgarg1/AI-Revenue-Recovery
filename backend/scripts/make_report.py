"""
Regenerate EVALUATION.md from the current database.

The numbers in the README, the dashboard, and the pitch video all come from
here, so there is exactly one place they can be wrong.
"""

import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analytics.report import (                              # noqa: E402
    full_report, render_markdown, render_run_environment,
)
from app.db import SessionLocal                                 # noqa: E402

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "EVALUATION.md"))
    parser.add_argument("--json", dest="json_out",
                        default=os.path.join(REPO_ROOT, "docs", "data", "results.json"))
    parser.add_argument("--env-out",
                        default=os.path.join(REPO_ROOT, "docs",
                                             "run-environment.md"))
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = full_report(db)
    finally:
        db.close()

    # LF explicitly. The default on Windows is CRLF, which makes the committed
    # file differ from a Linux regeneration for no reason and fails CI's
    # reproducibility check on line endings alone.
    LF = "\n"

    with open(args.out, "w", encoding="utf-8", newline=LF) as fh:
        fh.write(render_markdown(report))

    os.makedirs(os.path.dirname(args.env_out), exist_ok=True)
    with open(args.env_out, "w", encoding="utf-8", newline=LF) as fh:
        fh.write(render_run_environment(report))

    # results.json is checked by CI, so it carries only what the seed decides.
    # Message provenance and live link counts live alongside the environment
    # report, where a different answer is expected rather than a failure.
    deterministic = {k: v for k, v in report.items() if k != "delivery"}
    with open(args.json_out, "w", encoding="utf-8", newline=LF) as fh:
        json.dump(deterministic, fh, indent=2, default=str)

    env_json = os.path.join(os.path.dirname(args.json_out), "run-environment.json")
    with open(env_json, "w", encoding="utf-8", newline=LF) as fh:
        json.dump(report["delivery"], fh, indent=2, default=str)

    e = report["experiment"]
    print(f"Wrote {args.out}")
    print(f"Wrote {args.env_out}")
    print(f"Wrote {args.json_out}")
    print()
    print(f"  treatment  {e['treatment_rate']*100:5.1f}%  "
          f"({e['treatment_recovered']}/{e['treatment_n']})")
    print(f"  control    {e['control_rate']*100:5.1f}%  "
          f"({e['control_recovered']}/{e['control_n']})")
    print(f"  net lift   {e['net_lift']*100:+5.1f} pp  "
          f"[{e['ci_lower']*100:.1f}, {e['ci_upper']*100:.1f}]  "
          f"{'significant' if e['is_significant'] else 'NOT significant'}")
    print(f"  incremental Rs {e['incremental_recovered_paise']/100:,.0f}  "
          f"on spend Rs {e['intervention_cost_paise']/100:,.2f}  "
          f"= {e['roi']:.1f}x")
    print(f"  ledger     {report['audit']['records']} events, "
          f"valid={report['audit']['valid']}")


if __name__ == "__main__":
    main()

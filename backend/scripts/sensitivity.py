"""
Regenerate docs/sensitivity.md from the committed database.

The evaluation reports what the run produced. This reports how much of that
survives the assumptions being wrong, which is the question a reviewer asks
second and the one a buyer asks first.

    python backend/scripts/sensitivity.py
"""

import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analytics.sensitivity import SWEEP, sensitivity_report  # noqa: E402
from app.db import SessionLocal                                  # noqa: E402

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
LF = "\n"


def pp(x: float) -> str:
    return f"{x * 100:+.1f}"


def render(report: dict) -> str:
    c = report["committed"]
    params = report["parameters"]

    lines = [
        "# Sensitivity",
        "",
        "`docs/assumptions.md` lists seventy-three numbers we chose rather than",
        "measured. The headline result rests on them, so reporting it as though",
        "it were an observation would be the most misleading thing this project",
        "could do. What we have is not *\"+14.4 points\"* — it is",
        "*\"+14.4 points, if the base rates we picked are right.\"*",
        "",
        "This page moves each of those numbers across a wide range and reports",
        "what happens to the answer. Regenerate it with",
        "`python backend/scripts/sensitivity.py`.",
        "",
        "## Why this is a recomputation, not eighty re-runs",
        "",
        "No decision module imports the outcome oracle. The classifier, the",
        "ladder, the policy engine and the detector cannot see it, so perturbing",
        "a base rate cannot change which messages were sent — only whether the",
        "customer paid. The actions are held fixed and the outcomes re-decided.",
        "",
        "The architectural rule that keeps the experiment honest is the same one",
        "that makes this analysis affordable.",
        "",
        "## The committed result",
        "",
        "| | |",
        "| --- | --- |",
        f"| Net lift | **{pp(c['net_lift'])} pp** |",
        f"| 95% CI | {pp(c['ci_lower'])} → {pp(c['ci_upper'])} |",
        f"| Significant | {'yes' if c['is_significant'] else 'no'} |",
        "",
        "## What would have to be wrong",
        "",
    ]

    if report["conclusion_holds"]:
        lines += [
            f"**Nothing tested breaks it.** Every one of the {len(params)} "
            f"assumptions was moved from ×{min(SWEEP)} to ×{max(SWEEP)} of its "
            "committed value, one at a time, and the lift stayed significant "
            "throughout.",
            "",
        ]
    else:
        lines += [
            "The conclusion — a significant positive lift, not the exact figure —"
            " survives every assumption tested except these:",
            "",
            "| Assumption | Breaks at | In words |",
            "| --- | --- | --- |",
        ]
        for b in report["breakers"]:
            direction = "less" if b["breaking_point"] < 1 else "more"
            lines.append(
                f"| {b['label']} | ×{b['breaking_point']} | "
                f"every value would have to be **{abs(b['wrong_by_pct'])}% "
                f"{direction}** than we assumed, all at once |"
            )
        lines += [
            "",
            f"Every other assumption held across the entire range, ×{min(SWEEP)} "
            f"to ×{max(SWEEP)}.",
            "",
        ]

    lines += [
        "## Ranked by how much each moves the answer",
        "",
        "The first row is the one to attack first. A parameter that swings the",
        "lift by a tenth of a point is not worth arguing about.",
        "",
        "| Assumption | Swing | Lift range | Impact |",
        "| --- | --- | --- | --- |",
    ]

    for p in params:
        lines.append(
            f"| {p['label']} | {p['swing_pp']:.1f} pp | "
            f"{pp(p['low_lift'])} → {pp(p['high_lift'])} | {p['impact']} |"
        )

    lines += [
        "",
        f"{report['material_count']} of {len(params)} assumptions move the lift "
        "by more than two points. The rest are noise, and saying so is more",
        "useful than defending all seventy-three.",
        "",
        "## What this cannot tell you",
        "",
        "It varies our assumptions inside our model. If the *shape* of the model",
        "is wrong — if lift is not additive across touches, or if contacting",
        "someone twice annoys them into not paying — no amount of moving these",
        "numbers will show it. That is a limit of simulation, and the only cure",
        "is real outcome data.",
        "",
    ]
    return LF.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "docs",
                                                      "sensitivity.md"))
    parser.add_argument("--json", dest="json_out",
                        default=os.path.join(REPO_ROOT, "docs", "data",
                                             "sensitivity.json"))
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = sensitivity_report(db)
    finally:
        db.close()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline=LF) as fh:
        fh.write(render(report))

    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8", newline=LF) as fh:
        json.dump(report, fh, indent=2, default=str)

    print(f"Wrote {args.out}")
    print(f"Wrote {args.json_out}")
    print()
    c = report["committed"]
    print(f"  committed lift  {pp(c['net_lift'])} pp  "
          f"[{pp(c['ci_lower'])}, {pp(c['ci_upper'])}]")
    print(f"  material        {report['material_count']} of "
          f"{len(report['parameters'])} assumptions")
    if report["conclusion_holds"]:
        print("  nothing tested breaks the conclusion")
    else:
        for b in report["breakers"]:
            print(f"  breaks at x{b['breaking_point']}  {b['label']} "
                  f"({abs(b['wrong_by_pct'])}% off)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

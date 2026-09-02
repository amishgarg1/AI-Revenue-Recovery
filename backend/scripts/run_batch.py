"""
Run one full recovery batch over the seeded dataset.

Resets any previous run first, so this is safe to run repeatedly and always
produces the same result. Same seed, same clock, same numbers.
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.orchestrator import Orchestrator, reset_run_state   # noqa: E402
from app.db import SessionLocal                                   # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-reset", action="store_true",
                        help="continue from the current state instead of rewinding")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if not args.no_reset:
            reset_run_state(db)

        print("Running the recovery batch...")
        started = time.time()
        summary = Orchestrator(db).run()
        duration = time.time() - started

        stats = summary["stats"]
        print()
        print(f"  {stats.get('cases_total', 0)} cases over "
              f"{summary['ticks']} ticks ({summary['horizon_hours'] // 24} days)")
        print(f"  {stats.get('actions_sent', 0):>5} sent   "
              f"Rs {stats.get('spend_paise', 0) / 100:,.2f}")
        print(f"  {stats.get('actions_blocked', 0):>5} refused by a gate")
        print(f"  {stats.get('recovered', 0):>5} recovered   "
              f"Rs {stats.get('recovered_paise', 0) / 100:,.0f}")
        print()
        print(f"Completed in {duration:.1f}s. Run `make report` next.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

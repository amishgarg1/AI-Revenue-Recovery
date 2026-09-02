"""
Build demo.db from scratch.

Idempotent and deterministic: drop, recreate, regenerate from seed 42. Running
it twice produces identical bytes of data, which is what lets the committed
demo.db, the numbers in EVALUATION.md, and the numbers in the video all be the
same numbers.
"""

import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import clock                                    # noqa: E402
from app.db import Base, SessionLocal, engine                 # noqa: E402
from app.models import (                                      # noqa: E402
    Action, Case, Customer, Event, Invoice, Order, Payment,
)
from app.sim.generator import generate_dataset                # noqa: E402


def seed_db(seed: int = 42, quiet: bool = False) -> dict:
    def say(msg):
        if not quiet:
            print(msg)

    say("Dropping and recreating tables...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    say(f"Generating synthetic dataset (seed={seed})...")
    data = generate_dataset(seed=seed)

    db = SessionLocal()
    try:
        db.bulk_insert_mappings(Customer, data["customers"])
        db.bulk_insert_mappings(Order, data["orders"])
        db.bulk_insert_mappings(Payment, data["payments"])
        db.bulk_insert_mappings(Invoice, data["invoices"])

        # Cases carry the customer_id denormalised so the frequency cap can be
        # evaluated without a join on every one of ~57,000 gate checks.
        order_owner = {o["order_id"]: o["customer_id"] for o in data["orders"]}
        invoice_owner = {i["invoice_id"]: i["customer_id"] for i in data["invoices"]}
        for case in data["cases"]:
            case["customer_id"] = (
                order_owner.get(case["entity_id"])
                if case["entity_type"] == "order"
                else invoice_owner.get(case["entity_id"])
            )
        db.bulk_insert_mappings(Case, data["cases"])

        # Outreach from before this batch existed, so the frequency cap has a
        # history to respect rather than starting from a clean slate.
        db.bulk_insert_mappings(Action, data["prior_actions"])

        db.commit()

        counts = {
            "customers": len(data["customers"]),
            "orders": len(data["orders"]),
            "payments": len(data["payments"]),
            "invoices": len(data["invoices"]),
            "cases": len(data["cases"]),
            "prior_actions": len(data["prior_actions"]),
        }
        say("")
        for name, n in counts.items():
            say(f"  {n:>6}  {name}")
        say("")
        say("  Planted traps (each one exists to make a guardrail fire):")
        for name, n in data["traps"].items():
            say(f"  {n:>6}  {name}")
        say("")
        say(f"  Simulation window: {clock.iso(clock.BATCH_START)} "
            f"-> {clock.iso(clock.BATCH_END)}")
        say(f"  {clock.TICK_COUNT} ticks of {clock.TICK_HOURS}h")
        say("")
        say("Seeded. Run `make run-batch` next.")
        return {"counts": counts, "traps": data["traps"]}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the RecoverOS demo database")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    seed_db(seed=args.seed, quiet=args.quiet)

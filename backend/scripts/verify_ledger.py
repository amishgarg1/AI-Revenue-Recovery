"""
Recompute the audit chain from genesis and report where it diverges.

Exits non-zero on a broken chain so it can be wired into CI: an audit trail
whose integrity nobody checks automatically is an audit trail that quietly
stops being intact.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.ledger import verify_chain    # noqa: E402
from app.db import SessionLocal             # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        result = verify_chain(db)
    finally:
        db.close()

    print(f"events   : {result['records']}")
    print(f"chain    : {'VALID' if result['valid'] else 'BROKEN'}")

    if result["valid"]:
        print()
        print("Every event verifies against a fresh recomputation from genesis.")
        return 0

    print(f"broken   : {result['broken_count']} rows")
    print(f"first    : event #{result['first_break']}")
    print(f"ids      : {result['broken_at']}")
    print()
    print("A row was edited after it was written. Re-run `make demo` to rebuild.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

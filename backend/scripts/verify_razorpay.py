"""
Check the Razorpay test-mode integration before relying on it in a demo.

Mints one real payment link and prints the URL. Run this after putting keys in
`.env` — finding out the credentials are wrong while recording is not the time.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.razorpay_client.links import (      # noqa: E402
    RazorpayError, create_payment_link, has_credentials,
)


def main() -> int:
    if not has_credentials():
        print("RZP_KEY_ID and RZP_KEY_SECRET are not set.")
        print()
        print("The demo runs without them — payment links are simulated and")
        print("flagged as such in the database and the dashboard. Set them only")
        print("if you want live test-mode links in the recording.")
        return 1

    key_id = os.environ["RZP_KEY_ID"]
    if not key_id.startswith("rzp_test_"):
        # Worth being loud about. This script creates a real payment link.
        print(f"Refusing to run: RZP_KEY_ID is '{key_id[:12]}…', which is not a")
        print("test-mode key. RecoverOS is a simulation and must never be")
        print("pointed at live credentials.")
        return 2

    print(f"Using {key_id[:16]}… (test mode)")
    try:
        result = create_payment_link(
            amount_paise=10_000,   # ₹100
            customer={
                "name": "Integration Test",
                "email": "test@example.com",
                "phone": "+919876543210",
            },
            description="RecoverOS integration check",
            reference_id="recoveros_integration_check",
            recovery_class="TEST",
        )
    except RazorpayError as exc:
        print(f"Failed: {exc}")
        return 3

    print()
    print(f"  link   {result.get('short_url')}")
    print(f"  id     {result.get('id')}")
    print(f"  status {result.get('status')}")
    print()
    print("Open it in a browser to see the Razorpay checkout page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

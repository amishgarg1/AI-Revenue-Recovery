"""
Razorpay test-mode Payment Links.

Every recovery message needs a link the customer can actually pay through, so
this calls the real Razorpay API in test mode and uses the `short_url` it
returns. Minting six hundred of them would be rate-limited noise, so the
orchestrator mints a small budget of live links and simulates the rest — and
every link is stored with a flag saying which it is, so the dashboard and the
README can be precise about it rather than implying the whole batch is live.

With no keys configured the module degrades to simulated links and the batch
runs identically. A judge should not need our credentials to reproduce our
numbers.
"""

import os
from typing import Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "https://api.razorpay.com/v1"
TIMEOUT_SECONDS = 15

# Simulated links are visibly simulated. A fake link dressed up to look real is
# the kind of thing that loses a panel's trust for the rest of the demo.
SIMULATED_PREFIX = "https://rzp.io/simulated"


class RazorpayError(RuntimeError):
    pass


def has_credentials() -> bool:
    # RECOVEROS_OFFLINE forces simulated links regardless of configuration, so
    # a test run can never mint a real one. Importing litellm re-reads .env and
    # restores cleared keys, so removing them is not a reliable guard.
    if os.environ.get("RECOVEROS_OFFLINE"):
        return False
    return bool(os.environ.get("RZP_KEY_ID") and os.environ.get("RZP_KEY_SECRET"))


def create_payment_link(amount_paise: int, customer: dict, description: str,
                        reference_id: str, recovery_class: str = "") -> dict:
    """Create a real test-mode payment link. Raises if the API refuses."""
    if not has_credentials():
        raise RazorpayError("RZP_KEY_ID / RZP_KEY_SECRET are not set")

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "description": description[:250],
        "reference_id": reference_id,
        "customer": {
            "name": customer.get("name", ""),
            "email": customer.get("email", ""),
            "contact": customer.get("phone", ""),
        },
        # We own the messaging: consent, quiet hours, frequency caps and channel
        # choice are all decided by the policy engine. Letting Razorpay send its
        # own reminders would route around every one of those gates.
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "notes": {"source": "recoveros", "recovery_class": recovery_class},
    }

    response = requests.post(
        f"{BASE_URL}/payment_links",
        json=payload,
        auth=HTTPBasicAuth(os.environ["RZP_KEY_ID"], os.environ["RZP_KEY_SECRET"]),
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RazorpayError(f"{response.status_code}: {response.text[:300]}")
    return response.json()


def simulated_link(reference_id: str) -> str:
    return f"{SIMULATED_PREFIX}/{reference_id}"


def build_payment_link(amount_paise: int, customer: dict, reference_id: str,
                       description: str, recovery_class: str = "",
                       live: bool = False) -> Tuple[str, bool]:
    """
    Return `(url, is_real)`.

    Never raises: a payments API being unreachable must not take down a batch
    whose entire point is handling failure gracefully. A failed mint falls back
    to a simulated link and the caller records that it was simulated.
    """
    if not live:
        return simulated_link(reference_id), False

    try:
        result = create_payment_link(
            amount_paise=amount_paise,
            customer=customer,
            description=description,
            reference_id=reference_id,
            recovery_class=recovery_class,
        )
        url: Optional[str] = result.get("short_url")
        if url:
            return url, True
    except (RazorpayError, requests.RequestException):
        pass

    return simulated_link(reference_id), False

"""
Post a real Razorpay `payment.failed` webhook at the running API.

The batch is a simulation over a fixed horizon, which is what measuring a
policy needs. This is the answer to the next question - whether the decision
logic only works because a batch hands it a tidy world.

It signs the body the way Razorpay signs it (HMAC-SHA256 of the raw bytes, in
`X-Razorpay-Signature`) when `RZP_WEBHOOK_SECRET` is set, and posts unsigned
otherwise. The response says which happened; nothing here implies a check that
did not run.

    python backend/scripts/send_webhook.py
    python backend/scripts/send_webhook.py --reason issuer_down
    python backend/scripts/send_webhook.py --forge      # watch it get refused
    python backend/scripts/send_webhook.py --merchant merchant_uk_subs
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SAMPLE = os.path.join(REPO_ROOT, "examples", "payment_failed.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000/api/live/payment-failed")
    parser.add_argument("--file", default=SAMPLE)
    parser.add_argument("--reason", help="override error_reason to see a different lane")
    parser.add_argument("--amount", type=int, help="override the amount, in paise")
    parser.add_argument("--forge", action="store_true",
                        help="send a wrong signature, to watch it be refused")
    parser.add_argument("--merchant",
                        help="decide under this merchant's policy instead of "
                             "the default (see config/policy.yaml)")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as fh:
        payload = json.load(fh)

    entity = payload["payload"]["payment"]["entity"]
    if args.reason:
        entity["error_reason"] = args.reason
    if args.amount:
        entity["amount"] = args.amount

    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "X-Razorpay-Event-Id": "evt_local_demo"}

    secret = os.environ.get("RZP_WEBHOOK_SECRET")
    if secret:
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Razorpay-Signature"] = "0" * 64 if args.forge else signature
    elif args.forge:
        print("--forge needs RZP_WEBHOOK_SECRET set, or there is no check to fail.")
        return 1

    url = args.url
    if args.merchant:
        url += f"?merchant={args.merchant}"

    print(f"POST {url}")
    if args.merchant:
        print(f"  merchant      {args.merchant}")
    print(f"  error_reason  {entity['error_reason']}")
    print(f"  amount        Rs {entity['amount'] / 100:,.2f}")
    print(f"  signed        {'yes' if secret else 'no secret configured'}"
          f"{' (deliberately wrong)' if args.forge else ''}")
    print()

    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        detail = json.load(e).get("detail", e.reason)
        print(f"  {e.code}  {detail}")
        # A refused forgery is the endpoint working, not the script failing.
        return 0 if args.forge else 1
    except urllib.error.URLError as e:
        print(f"  Could not reach {args.url} - is 'make api' running? ({e.reason})")
        return 1

    action = result["action"]
    print(f"  recovery class  {result['recovery_class']}  (rule {result['rule_id']})")
    if action:
        # ASCII separators: a Windows console renders "·" as "?", and this
        # output is meant to be read over someone's shoulder.
        print(f"  next action     tier {action['tier']} | {action['channel']} | "
              f"Rs {action['cost_paise'] / 100:.2f}")
    else:
        print("  next action     none - the ladder is finished, spend nothing")
    print(f"  allowed         {result['allowed']}"
          f"{'   blocked by ' + result['blocked_by'] if result['blocked_by'] else ''}")
    print(f"  gates run       {len(result['gate_trail'])}")
    print(f"  latency         {result['latency_ms']} ms")
    print(f"  signature       verified={result['signature_verified']} "
          f"checked={result['signature_checked']}")
    print(f"  executed        {result['executed']}")
    print(f"  policy          {result.get('policy', 'default')}")
    print()

    for gate in result["gate_trail"]:
        mark = "  ok   " if gate["allowed"] else "  BLOCK"
        print(f"{mark} {gate['gate_id']}  {gate['name']:<18} {gate['detail']}")

    print()
    print(f"  recorded as live decision #{result['decision_id']} "
          f"({result['this_hash'][:16]}...)")
    print("  The simulation ledger is untouched - live decisions have their own "
          "chain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

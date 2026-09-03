"""
Render each placed voice call to audio.

A Tier-3 action is a real call with a real script behind it, generated and
validated by the batch whether or not this runs. What this adds is the ability
to hear one.

**One clip per case.** An earlier version rendered a single specimen with
invented values and played it on every voice case, so the page read "Namaste
Sanya Bose ji ... one lakh thirty one thousand rupees" while the speaker said
"Meera Iyer ... one lakh forty one thousand". A note explaining the discrepancy
was not a fix; the audio has to be the case's own call.

Needs SARVAM_API_KEY. Without it nothing is rendered, the manifest records
that, and the dashboard shows each script with a line saying no recording
exists — rather than a player that misrepresents what it is playing.

    python backend/scripts/render_voice.py
    python backend/scripts/render_voice.py --limit 5
    python backend/scripts/render_voice.py --speaker neha
"""

import argparse
import base64
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests                                              # noqa: E402

from app.db import SessionLocal                              # noqa: E402
from app.llm.speech import to_speech                         # noqa: E402
from app.models import Action, Customer                      # noqa: E402

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"

# Providers retire TTS models the way they retire chat models — bulbul:v2 went
# away mid-build and every call started 400ing. Both are overridable.
SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "bulbul:v3")
SPEAKER = os.environ.get("SARVAM_SPEAKER", "priya")

# Hindi and Hinglish scripts are both romanised, and a Hindi voice reads them
# the way a caller would actually hear them.
LANGUAGE_CODE = {"en": "en-IN", "hi": "hi-IN", "hinglish": "hi-IN"}

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT_DIR = os.path.join(REPO_ROOT, "frontend", "public", "voice")


def voice_calls(db):
    """Every voice message this run actually placed, with its language."""
    language = {c.customer_id: c.language_pref for c in db.query(Customer)}
    calls = [
        a for a in db.query(Action)
        if a.channel == "voice" and a.status == "SENT"
        and a.message_body and (a.tick or 0) >= 0
    ]
    calls.sort(key=lambda a: a.case_id)
    return [
        {
            "case_id": a.case_id,
            "language": language.get(a.customer_id, "en"),
            "written": a.message_body,
            "spoken": to_speech(a.message_body),
        }
        for a in calls
    ]


def synthesise(key: str, clip: dict, speaker: str, path: str) -> bool:
    response = requests.post(
        SARVAM_URL,
        headers={"api-subscription-key": key},
        json={
            "inputs": [clip["spoken"]],
            "target_language_code": LANGUAGE_CODE.get(clip["language"], "en-IN"),
            "speaker": speaker,
            "model": SARVAM_MODEL,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        print(f"  {clip['case_id']}  {response.status_code}: "
              f"{response.text[:130]}")
        return False

    with open(path, "wb") as fh:
        fh.write(base64.b64decode(response.json()["audios"][0]))
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=OUT_DIR)
    parser.add_argument("--speaker", default=SPEAKER)
    parser.add_argument("--limit", type=int, default=None,
                        help="render only the first N calls")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        clips = voice_calls(db)
    finally:
        db.close()

    if not clips:
        print("No voice calls in this batch. Run the batch first.")
        return 1

    if args.limit:
        clips = clips[:args.limit]

    print(f"{len(clips)} voice calls to render "
          f"({', '.join(sorted({c['language'] for c in clips}))}).")
    print()

    os.makedirs(args.out, exist_ok=True)
    key = os.environ.get("SARVAM_API_KEY")
    manifest = {}

    for clip in clips:
        entry = {
            "language": clip["language"],
            "written": clip["written"],
            "spoken": clip["spoken"],
            "audio": None,
        }
        if key:
            path = os.path.join(args.out, f"{clip['case_id']}.wav")
            if synthesise(key, clip, args.speaker, path):
                entry["audio"] = f"/voice/{clip['case_id']}.wav"
                size = os.path.getsize(path) // 1024
                print(f"  {clip['case_id']}  {clip['language']:9} {size:>5} KB")
        manifest[clip["case_id"]] = entry

    with open(os.path.join(args.out, "manifest.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"speaker": args.speaker, "model": SARVAM_MODEL,
                   "clips": manifest}, fh, indent=2)

    rendered = sum(1 for e in manifest.values() if e["audio"])
    print()
    if not key:
        print("SARVAM_API_KEY is not set, so no audio was rendered. Every script")
        print("is still generated and validated by the batch; the dashboard shows")
        print("the text and says no recording exists, rather than playing one")
        print("that belongs to a different case.")
    else:
        print(f"Rendered {rendered} of {len(clips)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

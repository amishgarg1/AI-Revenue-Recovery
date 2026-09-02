"""
Running a batch, live.

`/api/batch/stream` is a Server-Sent Events endpoint: the orchestrator emits an
event per tick and the browser watches cases move through classification, the
gates, and delivery in real time. Watching a guardrail refuse an action as it
happens is considerably more convincing than reading that it did.
"""

import json
import queue
import threading
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.orchestrator import Orchestrator, reset_run_state as _reset
from app.db import SessionLocal, get_db

router = APIRouter(prefix="/api", tags=["batch"])


@router.post("/batch/run")
def run_batch(db: Session = Depends(get_db), reset: bool = True):
    """Run a full batch synchronously and return the summary."""
    if reset:
        _reset(db)
    started = time.time()
    summary = Orchestrator(db).run()
    summary["duration_seconds"] = round(time.time() - started, 2)
    return summary


@router.get("/batch/stream")
def stream_batch(reset: bool = True):
    """
    Run a batch on a worker thread and stream its progress as SSE.

    The orchestrator gets its own session: SQLAlchemy sessions are not
    thread-safe, and sharing the request's session would corrupt state in a way
    that only shows up under load.
    """
    events: "queue.Queue[dict]" = queue.Queue()

    def worker():
        db = SessionLocal()
        try:
            if reset:
                _reset(db)
            summary = Orchestrator(db, emit=events.put).run()
            events.put({"type": "done", "summary": summary})
        except Exception as exc:  # a dead stream is worse than an error message
            events.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            db.close()
            events.put({"type": "__eof__"})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        while True:
            event = events.get()
            if event.get("type") == "__eof__":
                return
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and most PaaS proxies buffer by default, which turns a live
            # stream into one delivery at the end.
            "X-Accel-Buffering": "no",
        },
    )

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Point the app at a throwaway database *before* app.db is imported anywhere.
# The suite creates and drops every table, so sharing the committed demo.db
# would quietly empty it and leave a repo that serves no data on a clean clone.
os.environ.setdefault(
    "RECOVEROS_DB_PATH",
    os.path.join(tempfile.gettempdir(), "recoveros_test.db"),
)

# Tests must never reach a provider. Once real keys are configured the
# orchestrator would make live LLM calls and mint real payment links inside the
# suite - slow, flaky, and billed.
#
# Unsetting the keys does not work: importing litellm calls `load_dotenv()`
# itself, so every key the suite removes is quietly restored the moment
# anything touches the LLM client. That cost 65 seconds a run in network
# timeouts before it was understood. This flag is checked at call time and
# nothing else can undo it.
os.environ["RECOVEROS_OFFLINE"] = "1"

from app.core import ledger                       # noqa: E402
from app.core.detector import detector            # noqa: E402
from app.db import DB_PATH, Base, SessionLocal, engine   # noqa: E402

assert not DB_PATH.endswith(os.path.join("backend", "demo.db")), (
    "tests must never run against the committed demo.db"
)


@pytest.fixture(autouse=True)
def clean_detector():
    """
    The issuer-health detector is a module-level singleton, so a test that
    loads an outage into it leaks that outage into every test that runs
    afterwards — G08 starts blocking silent retries in tests that never
    mentioned an issuer. Clearing it between tests keeps the suite
    order-independent.
    """
    detector.reset()
    yield
    detector.reset()


@pytest.fixture
def db():
    """
    A fresh database per test.

    The ledger caches the chain head in-process for speed, so it has to be
    reset alongside the tables — otherwise a test inherits the previous test's
    head and every hash it writes chains to a row that no longer exists.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ledger.reset_head_cache()

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        ledger.reset_head_cache()

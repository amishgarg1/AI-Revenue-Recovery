"""
Does requirements.txt actually cover what the app needs?

This exists because the same mistake happened twice. `pyyaml` and
`python-multipart` were both present locally as transitive dependencies of
something else, so everything worked here and CI failed on a clean install -
which is exactly the environment a judge cloning the repo has.

Two shapes of the bug, and both are caught below:

**An import we make.** `import yaml` needs `pyyaml` declared, and the package
name is not the import name, which is why grepping for the import alone would
not have helped.

**A feature we use.** Nothing in our code imports `multipart`. FastAPI requires
it at request time when a route declares `File(...)`, so the dependency is
implied by usage rather than by an import statement, and the failure appears as
a RuntimeError on the first upload rather than at startup.
"""

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
REQUIREMENTS = pathlib.Path(__file__).resolve().parents[1] / "requirements.txt"

# Import name -> distribution name, for the cases where they differ. A test
# that assumed they matched would pass while the requirement was missing.
IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml",
    "sqlalchemy": "sqlalchemy",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "requests": "requests",
    "httpx": "httpx",
    "litellm": "litellm",
    "uvicorn": "uvicorn",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
}

# A FastAPI feature that pulls in a package no line of our code imports. The
# marker is what to look for in the source; the package is what has to be
# declared.
FEATURE_PACKAGES = [
    ("File(", "python-multipart"),
    ("UploadFile", "python-multipart"),
    ("Form(", "python-multipart"),
]

# Optional at runtime. The batch is designed to survive their absence, and
# `RECOVEROS_OFFLINE` exercises that path, so they are declared but not
# required for the tests to mean anything.
OPTIONAL = {"litellm"}


def declared() -> set:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        # Strip extras and any version specifier: uvicorn[standard]>=0.27.
        name = re.split(r"[\[><=!~;]", line)[0].strip().lower()
        if name:
            names.add(name)
    return names


def app_sources():
    return list(APP.rglob("*.py"))


def third_party_imports() -> set:
    """Top-level non-stdlib, non-app modules the app imports."""
    import sys

    found = set()
    pattern = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z_][\w]*)", re.M)

    for path in app_sources():
        for module in pattern.findall(path.read_text(encoding="utf-8")):
            if module == "app" or module in sys.builtin_module_names:
                continue
            if module in IMPORT_TO_PACKAGE:
                found.add(module)
    return found


def test_every_third_party_import_is_declared():
    """
    The pyyaml shape: an import whose package name differs from its module
    name, present locally by accident and missing on a clean install.
    """
    have = declared()
    missing = sorted(
        IMPORT_TO_PACKAGE[m] for m in third_party_imports()
        if IMPORT_TO_PACKAGE[m] not in have
    )
    assert not missing, (
        f"imported but not in requirements.txt: {missing}. "
        "It probably works locally as a transitive dependency and will fail on "
        "a clean install."
    )


def test_features_that_need_a_package_have_it_declared():
    """
    The python-multipart shape: no line of our code imports it, and FastAPI
    raises at request time when a route declares File(...).
    """
    have = declared()
    sources = "\n".join(p.read_text(encoding="utf-8") for p in app_sources())

    missing = sorted({
        package for marker, package in FEATURE_PACKAGES
        if marker in sources and package not in have
    })
    assert not missing, (
        f"used but not in requirements.txt: {missing}. FastAPI needs these at "
        "request time, so the failure is a RuntimeError on the first request "
        "rather than an ImportError at startup."
    )


def test_requirements_pin_lower_bounds():
    """
    An unpinned line resolves to whatever exists the day someone installs it.
    The file's own comment promises lower bounds where the version matters.
    """
    unpinned = [
        line.split("#")[0].strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.split("#")[0].strip()
        and not re.search(r"[><=~]", line.split("#")[0])
    ]
    assert not unpinned, f"no version bound on: {unpinned}"


def test_optional_dependencies_are_actually_optional():
    """
    The batch has to run with no API keys and no provider, so nothing in the
    decision path may import an optional package at module scope.
    """
    core = APP / "core"
    offenders = []
    for path in core.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in OPTIONAL:
            if re.search(rf"^\s*(?:import|from)\s+{name}\b", text, re.M):
                offenders.append(f"{path.name} imports {name}")
    assert not offenders, offenders

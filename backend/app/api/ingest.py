"""
Plan against a merchant's own export.

The fair question a reviewer asks about a simulation is "what would this do on
our data", and until now there was no way to answer it. `POST /api/ingest/plan`
takes a CSV of failed payments and returns what the policy would do to it -
same classifier, same ladder, same eleven gates.

Nothing is stored. A payment export is customer data: it is parsed in memory,
planned against, and dropped. The response carries counts and money, never a
row. That is a deliberate design choice rather than an omission - there is no
retention question to answer and no breach surface to defend.
"""

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.ingest.plan import build_plan
from app.ingest.reader import IngestError, read_csv

router = APIRouter(prefix="/api", tags=["ingest"])

# A plan is computed synchronously, so an unbounded upload would hold a request
# open for minutes. Large enough for a real month of failures.
MAX_BYTES = 8 * 1024 * 1024


@router.post("/ingest/plan")
async def plan(
    file: UploadFile = File(...),
    merchant: str = Query("", description="plan under this merchant's policy"),
    problems: int = Query(20, le=200,
                          description="how many rejected rows to return"),
):
    """
    Read a CSV of failed payments and report what the policy would do.

    Row-level problems come back with line numbers, because "17 rows were
    invalid" is useless to somebody with a forty-thousand-line export.
    """
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is {len(raw) / 1e6:.1f} MB; the limit is "
                   f"{MAX_BYTES / 1e6:.0f} MB. Split it and plan each part.")

    try:
        # utf-8-sig strips the BOM Excel writes, which otherwise makes the
        # first header unmatchable and every row fail for a missing id.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File is not UTF-8 text. Re-export it as CSV UTF-8.")

    try:
        read = read_csv(text)
    except IngestError as e:
        # A file we cannot read is the caller's to fix, and the message says
        # what was missing and which headers were found.
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "filename": file.filename,
        "rows_read": read.total_lines,
        "rows_usable": len(read.rows),
        "rows_rejected": len(read.problems),
        "amount_unit": read.amount_unit,
        "mapping": read.mapping,
        "unmapped_headers": read.unmapped_headers,
        "problems": [
            {"line": p.line, "column": p.column, "problem": p.problem}
            for p in read.problems[:problems]
        ],
        "plan": build_plan(read.rows, merchant_id=merchant or None),
        "stored": False,
    }

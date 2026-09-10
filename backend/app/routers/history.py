"""On-demand EOD history fetching for explicitly named symbols.

Backs the "Add Stock Data" page, so pulling a new ticker no longer means
dropping to the CLI.
"""
from datetime import date, timedelta

import dbservice_client as dbs
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import db_session
from app.logging_config import get_logger
from app.services import history_service, symbol_service, universe_service

log = get_logger(__name__)

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


class FetchRequest(BaseModel):
    symbols: list[str] = Field(
        ..., min_length=1, description="TICKER.EXCHANGE, e.g. AAPL.US. Bare ticker assumes .US"
    )
    from_date: date | None = Field(None, description="Range start. Defaults to one year back.")
    to_date: date | None = Field(None, description="Range end. Defaults to today.")
    incremental: bool = Field(
        False, description="Resume each symbol after its newest stored bar; avoids duplicates."
    )
    dry_run: bool = Field(False, description="Return the plan without fetching or ingesting.")


@router.get("/coverage")
def get_coverage(session: dbs.Session = Depends(db_session)):
    """What eod_prices already holds, per symbol.

    `duplicates` is rows minus distinct days - non-zero means overlapping
    ranges were ingested more than once.
    """
    df = history_service.stored_coverage(session)
    if df.empty:
        return []
    out = df.copy()
    out["first"] = out["first"].astype(str)
    out["last"] = out["last"].astype(str)
    return out.to_dict(orient="records")


@router.get("/symbols")
def list_symbols(session: dbs.Session = Depends(db_session)):
    """Symbols that have stored price history, for populating a picker."""
    return symbol_service.available_symbols(session)


@router.get("/universe")
def list_universe(session: dbs.Session = Depends(db_session)):
    """Stored symbols paired with their asset class, for grouping a picker.

    Separate from `/symbols` because the asset class comes from the universe
    CSVs rather than from `eod_prices`, which stores no such column. Symbols
    that appear in no universe file come back as "other".
    """
    return universe_service.classify(symbol_service.available_symbols(session))


@router.get("/history")
def symbol_history(
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
    session: dbs.Session = Depends(db_session),
):
    """Price series and performance statistics for a single symbol.

    This is the instrument's own performance over the window - it takes no
    account of when or whether you held it.
    """
    if not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")
    ticker, _, _ = symbol.strip().partition(".")
    return symbol_service.get_symbol_history(session, ticker, from_date, to_date)


@router.post("/fetch")
def fetch_history(req: FetchRequest, session: dbs.Session = Depends(db_session)):
    """Fetch EOD history for the named symbols and ingest it."""
    try:
        pairs = history_service.parse_symbols(req.symbols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not pairs:
        raise HTTPException(status_code=400, detail="No usable symbols supplied")

    to_date = req.to_date or date.today()
    from_date = req.from_date or (to_date - timedelta(days=365))
    if from_date > to_date:
        raise HTTPException(
            status_code=400, detail=f"from_date ({from_date}) is after to_date ({to_date})"
        )

    already = history_service.latest_stored(session, pairs) if req.incremental else {}
    plan, skipped = history_service.build_plan(pairs, from_date, to_date, already)

    payload = {
        "plan": [item.as_dict() for item in plan],
        "skipped": skipped,
        "dry_run": req.dry_run,
        "ingested": 0,
        "per_symbol": {},
        "failed": {},
        "no_data": {},
        "partition_days": 0,
    }

    if req.dry_run or not plan:
        if not plan:
            log.info("Nothing to fetch (%d already current)", len(skipped))
        return payload

    payload.update(history_service.run_plan(session, plan))
    return payload

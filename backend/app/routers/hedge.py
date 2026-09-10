"""Dynamic hedge-ratio analysis between two stored symbols.

Backs the "Static analysis SPY QQQ" page: compares a fixed OLS hedge ratio
against a rolling-window one and a Bayesian DLM whose beta is a latent state.
"""
from datetime import date

import dbservice_client as dbs
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import db_session
from app.logging_config import get_logger
from app.services import hedge_service

log = get_logger(__name__)

router = APIRouter(prefix="/api/hedge", tags=["hedge"])


@router.get("/analysis")
def hedge_ratio_analysis(
    y_symbol: str = Query("QQQ", description="Asset being hedged (the regressand)"),
    x_symbol: str = Query("SPY", description="Hedge instrument (the regressor)"),
    from_date: date | None = None,
    to_date: date | None = None,
    test_fraction: float = Query(0.20, gt=0.0, lt=0.9),
    rolling_window: int = Query(60, ge=5, le=500),
    discount: float = Query(
        0.70, gt=0.0, le=1.0,
        description="DLM memory: lower forgets faster, so beta tracks regime "
                    "changes more sharply but reacts more to noise.",
    ),
    session: dbs.Session = Depends(db_session),
):
    """Static vs rolling vs DLM hedge ratio, evaluated out of sample.

    Both symbols must already have stored history; this reads `eod_prices`
    and never fetches from the vendor.
    """
    result = hedge_service.hedge_analysis(
        session,
        y_symbol=y_symbol,
        x_symbol=x_symbol,
        from_date=from_date,
        to_date=to_date,
        test_fraction=test_fraction,
        rolling_window=rolling_window,
        discount=discount,
    )
    if "error" in result:
        # 422 rather than 404: the symbols may well exist, but the requested
        # window does not give enough overlapping days to fit and then test.
        raise HTTPException(status_code=422, detail=result)
    return result

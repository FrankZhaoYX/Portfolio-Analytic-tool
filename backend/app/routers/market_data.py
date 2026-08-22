from datetime import date
from enum import Enum

import dbservice_client as dbs
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import db_session
from app.services import market_data_service

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


class RefreshScope(str, Enum):
    EOD = "eod"
    QUOTES = "quotes"
    FUNDAMENTALS = "fundamentals"
    ALL = "all"


class RefreshRequest(BaseModel):
    scope: RefreshScope = RefreshScope.ALL
    from_date: date | None = None
    to_date: date | None = None


@router.post("/refresh")
def refresh_market_data(req: RefreshRequest, session: dbs.Session = Depends(db_session)):
    pairs = market_data_service.get_portfolio_symbols(session)
    result: dict[str, int] = {}

    if req.scope in (RefreshScope.EOD, RefreshScope.ALL):
        result["eod_rows"] = market_data_service.refresh_eod_prices(
            session, pairs, req.from_date, req.to_date
        )
    if req.scope in (RefreshScope.QUOTES, RefreshScope.ALL):
        result["quote_rows"] = market_data_service.refresh_quotes(session, pairs)
    if req.scope in (RefreshScope.FUNDAMENTALS, RefreshScope.ALL):
        result["fundamentals_rows"] = market_data_service.refresh_fundamentals(session, pairs)

    return result

from datetime import date

import dbservice_client as dbs
from fastapi import APIRouter, Depends

from app.dependencies import db_session
from app.services import performance_service

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("")
def get_performance(
    from_date: date | None = None,
    to_date: date | None = None,
    session: dbs.Session = Depends(db_session),
):
    return performance_service.get_performance_summary(session, from_date=from_date, to_date=to_date)

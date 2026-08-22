from datetime import date

import dbservice_client as dbs
from fastapi import APIRouter, Depends

from app.dependencies import db_session
from app.services import positions_service

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("")
def get_positions(session: dbs.Session = Depends(db_session)):
    return positions_service.get_positions(session)


@router.get("/pnl-history")
def get_pnl_history(from_date: date | None = None, session: dbs.Session = Depends(db_session)):
    return positions_service.get_pnl_history(session, from_date=from_date)

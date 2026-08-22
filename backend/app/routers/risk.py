import dbservice_client as dbs
from fastapi import APIRouter, Depends

from app.dependencies import db_session
from app.services import risk_service

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/summary")
def get_risk_summary(session: dbs.Session = Depends(db_session)):
    return risk_service.get_risk_summary(session)


@router.get("/correlation")
def get_correlation(session: dbs.Session = Depends(db_session)):
    return risk_service.get_correlation_matrix(session)

import dbservice_client as dbs
from fastapi import APIRouter, Depends

from app.dependencies import db_session
from app.models.allocation import AllocationDimension
from app.services import allocation_service

router = APIRouter(prefix="/api/allocation", tags=["allocation"])


@router.get("")
def get_allocation(
    dimension: AllocationDimension = AllocationDimension.ASSETTYPE,
    session: dbs.Session = Depends(db_session),
):
    return allocation_service.get_allocation(session, dimension)

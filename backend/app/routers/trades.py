import io

import dbservice_client as dbs
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.dependencies import db_session
from app.models.trade import TradeIn
from app.services import trades_service

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.post("")
def create_trade(trade: TradeIn, session: dbs.Session = Depends(db_session)):
    record = trades_service.insert_trade(session, trade)
    return record


@router.post("/upload")
async def upload_trades(file: UploadFile, session: dbs.Session = Depends(db_session)):
    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
        count = trades_service.insert_trades_csv(session, df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"inserted": count}


@router.get("")
def get_trades(limit: int = 200, session: dbs.Session = Depends(db_session)):
    df = trades_service.list_trades(session, limit=limit)
    return df.to_dict(orient="records")

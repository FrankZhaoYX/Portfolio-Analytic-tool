from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeIn(BaseModel):
    symbol: str
    exchange: str
    side: Side
    qty: float = Field(gt=0, description="Unsigned quantity - sign is derived from side")
    price: float = Field(gt=0)
    tradedate: datetime
    fees: float = 0.0
    currency: str = "USD"
    notes: str = ""


class TradeOut(BaseModel):
    tradeid: str
    tradedate: datetime
    symbol: str
    exchange: str
    side: Side
    qty: float
    price: float
    fees: float
    currency: str
    notes: str
    createdat: datetime

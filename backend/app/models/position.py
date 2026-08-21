from datetime import date

from pydantic import BaseModel


class Position(BaseModel):
    symbol: str
    exchange: str
    qty: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    weight_pct: float


class RealizedPnlEntry(BaseModel):
    symbol: str
    close_date: date
    qty: float
    proceeds: float
    cost_basis: float
    realized_pnl: float


class PnlHistoryPoint(BaseModel):
    as_of: date
    market_value: float
    unrealized_pnl: float
    realized_pnl_cum: float

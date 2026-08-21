from enum import Enum

from pydantic import BaseModel


class AllocationDimension(str, Enum):
    ASSETTYPE = "assettype"
    SECTOR = "sector"
    COUNTRY = "country"
    SYMBOL = "symbol"


class AllocationSlice(BaseModel):
    label: str
    market_value: float
    weight_pct: float


class AllocationBreakdown(BaseModel):
    dimension: AllocationDimension
    slices: list[AllocationSlice]

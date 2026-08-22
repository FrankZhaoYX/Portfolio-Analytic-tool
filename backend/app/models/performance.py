from datetime import date

from pydantic import BaseModel


class PerformancePoint(BaseModel):
    as_of: date
    portfolio_cum_return: float
    benchmark_cum_return: float | None = None


class PerformanceSummary(BaseModel):
    twr: float
    mwr: float | None = None
    start_date: date
    end_date: date
    points: list[PerformancePoint]

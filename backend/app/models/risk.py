from pydantic import BaseModel


class RiskSummary(BaseModel):
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    var_historical_95: float
    var_parametric_95: float


class CorrelationMatrix(BaseModel):
    symbols: list[str]
    matrix: list[list[float]]

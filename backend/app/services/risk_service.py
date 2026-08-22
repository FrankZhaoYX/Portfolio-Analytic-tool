import numpy as np
import dbservice_client as dbs
import pandas as pd

from app.config import settings
from app.db.tables import EOD_PRICES, TRADES
from app.models.risk import CorrelationMatrix, RiskSummary
from app.services.analytics_common import build_daily_valuation, daily_returns

TRADING_DAYS = 252


def get_risk_summary(session: dbs.Session) -> RiskSummary:
    trades_df = session.query_sql(query=f"SELECT * FROM {TRADES}", return_as="pandas")
    if trades_df.empty:
        return RiskSummary(
            annualized_volatility=0.0, sharpe_ratio=0.0, max_drawdown=0.0,
            var_historical_95=0.0, var_parametric_95=0.0,
        )

    symbols = ",".join(f"'{s}'" for s in trades_df["symbol"].unique())
    prices_df = session.query_sql(
        query=f"SELECT * FROM {EOD_PRICES} WHERE symbol IN ({symbols})",
        return_as="pandas",
    )
    valuation = build_daily_valuation(trades_df, prices_df)
    returns = daily_returns(valuation)

    if returns.empty:
        return RiskSummary(
            annualized_volatility=0.0, sharpe_ratio=0.0, max_drawdown=0.0,
            var_historical_95=0.0, var_parametric_95=0.0,
        )

    vol = float(returns.std() * np.sqrt(TRADING_DAYS))
    mean_daily = float(returns.mean())
    std_daily = float(returns.std())
    rf_daily = settings.risk_free_rate / TRADING_DAYS
    sharpe = float((mean_daily - rf_daily) / std_daily * np.sqrt(TRADING_DAYS)) if std_daily else 0.0

    cum = (1.0 + returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    max_dd = float(drawdown.min())

    var_hist = float(-np.percentile(returns, 5))
    var_param = float(-(mean_daily + std_daily * -1.645))

    return RiskSummary(
        annualized_volatility=vol,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        var_historical_95=var_hist,
        var_parametric_95=var_param,
    )


def get_correlation_matrix(session: dbs.Session) -> CorrelationMatrix:
    trades_df = session.query_sql(query=f"SELECT DISTINCT symbol FROM {TRADES}", return_as="pandas")
    if trades_df.empty:
        return CorrelationMatrix(symbols=[], matrix=[])

    symbols = trades_df["symbol"].unique().tolist()
    symlist = ",".join(f"'{s}'" for s in symbols)
    prices_df = session.query_sql(
        query=f"SELECT * FROM {EOD_PRICES} WHERE symbol IN ({symlist})",
        return_as="pandas",
    )
    if prices_df.empty:
        return CorrelationMatrix(symbols=symbols, matrix=[])

    prices_df["pxdate"] = pd.to_datetime(prices_df["pxdate"]).dt.normalize()
    wide = prices_df.pivot_table(index="pxdate", columns="symbol", values="close").sort_index()
    rets = wide.pct_change().dropna(how="all")
    corr = rets.corr().reindex(index=symbols, columns=symbols)

    return CorrelationMatrix(
        symbols=symbols,
        matrix=corr.fillna(0.0).values.tolist(),
    )

from datetime import date

import dbservice_client as dbs
import pandas as pd
from pyxirr import xirr

from app.config import settings
from app.db.tables import EOD_PRICES, TRADES
from app.models.performance import PerformancePoint, PerformanceSummary
from app.services.analytics_common import build_daily_valuation, daily_returns


def _benchmark_series(session: dbs.Session, from_date: date, to_date: date) -> pd.Series:
    bench_symbol, _, _ = settings.benchmark_symbol.partition(".")
    df = session.query_sql(
        query=(
            f"SELECT * FROM {EOD_PRICES} WHERE symbol = '{bench_symbol.upper()}' "
            f"AND date >= '{from_date.isoformat()}' AND date <= '{to_date.isoformat()}'"
        ),
        return_as="pandas",
    )
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values("date").set_index("date")
    return df["close"] / df["close"].iloc[0] - 1.0


def get_performance_summary(
    session: dbs.Session,
    from_date: date | None = None,
    to_date: date | None = None,
) -> PerformanceSummary:
    trades_df = session.query_sql(query=f"SELECT * FROM {TRADES}", return_as="pandas")
    if trades_df.empty:
        today = date.today()
        return PerformanceSummary(twr=0.0, mwr=None, start_date=today, end_date=today, points=[])

    symbols = ",".join(f"`{s}" for s in trades_df["symbol"].unique())
    prices_df = session.query_sql(
        query=f"SELECT * FROM {EOD_PRICES} WHERE symbol IN ({symbols})",
        return_as="pandas",
    )

    valuation = build_daily_valuation(trades_df, prices_df)
    if from_date:
        valuation = valuation[valuation.index >= pd.Timestamp(from_date)]
    if to_date:
        valuation = valuation[valuation.index <= pd.Timestamp(to_date)]

    if valuation.empty:
        today = date.today()
        return PerformanceSummary(twr=0.0, mwr=None, start_date=today, end_date=today, points=[])

    returns = daily_returns(valuation)
    twr = float((1.0 + returns).prod() - 1.0) if not returns.empty else 0.0

    mwr = None
    cash_flows = valuation["cash_flow"].copy()
    last_date = valuation.index[-1]
    final_value = valuation["market_value"].iloc[-1]
    flow_dates = list(cash_flows[cash_flows.abs() > 1e-9].index) + [last_date]
    flow_amounts = [-amt for amt in cash_flows[cash_flows.abs() > 1e-9].tolist()] + [final_value]
    if len(flow_dates) >= 2 and any(a < 0 for a in flow_amounts) and any(a > 0 for a in flow_amounts):
        try:
            mwr = xirr(dict(zip(flow_dates, flow_amounts)))
        except Exception:
            mwr = None

    start_date = valuation.index[0].date()
    end_date = valuation.index[-1].date()
    benchmark = _benchmark_series(session, start_date, end_date)

    portfolio_cum = valuation["market_value"] / valuation["market_value"].iloc[0] - 1.0
    points = [
        PerformancePoint(
            as_of=idx.date(),
            portfolio_cum_return=float(portfolio_cum.loc[idx]),
            benchmark_cum_return=float(benchmark.loc[idx]) if idx in benchmark.index else None,
        )
        for idx in valuation.index
    ]

    return PerformanceSummary(twr=twr, mwr=mwr, start_date=start_date, end_date=end_date, points=points)

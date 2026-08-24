from datetime import date

import dbservice_client as dbs
import pandas as pd
from pyxirr import xirr

from app.config import settings
from app.db.tables import EOD_PRICES, TRADES
from app.logging_config import get_logger
from app.models.performance import PerformancePoint, PerformanceSummary
from app.services.analytics_common import build_daily_valuation, daily_returns

log = get_logger(__name__)


def _benchmark_series(session: dbs.Session, from_date: date, to_date: date) -> pd.Series:
    bench_symbol, _, _ = settings.benchmark_symbol.partition(".")
    df = session.query_sql(
        query=(
            f"SELECT * FROM {EOD_PRICES} WHERE symbol = '{bench_symbol.upper()}' "
            f"AND pxdate >= '{from_date.isoformat()}' AND pxdate <= '{to_date.isoformat()}'"
        ),
        return_as="pandas",
    )
    if df.empty:
        # Silent until now: the chart just rendered a flat/absent benchmark line
        # with no indication the symbol had never been ingested.
        log.warning(
            "No benchmark data for %s between %s and %s - run a market-data "
            "refresh to ingest it, or change BENCHMARK_SYMBOL",
            settings.benchmark_symbol,
            from_date,
            to_date,
        )
        return pd.Series(dtype=float)
    df["pxdate"] = pd.to_datetime(df["pxdate"]).dt.normalize()
    # Re-ingesting an overlapping date range appends rather than replaces, so a
    # symbol can hold several rows per day. Left in place, the duplicated index
    # makes .loc[date] return a Series instead of a scalar further down.
    before = len(df)
    df = df.sort_values("pxdate").drop_duplicates(subset="pxdate", keep="last")
    if len(df) < before:
        log.warning(
            "Benchmark %s had %d duplicate row(s) - using the last per day",
            settings.benchmark_symbol,
            before - len(df),
        )
    df = df.set_index("pxdate")
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

    symbols = ",".join(f"'{s}'" for s in trades_df["symbol"].unique())
    prices_df = session.query_sql(
        query=f"SELECT * FROM {EOD_PRICES} WHERE symbol IN ({symbols})",
        return_as="pandas",
    )

    valuation = build_daily_valuation(trades_df, prices_df)
    if valuation.empty:
        today = date.today()
        return PerformanceSummary(twr=0.0, mwr=None, start_date=today, end_date=today, points=[])

    if from_date:
        valuation = valuation[valuation.index >= pd.Timestamp(from_date)]
    if to_date:
        valuation = valuation[valuation.index <= pd.Timestamp(to_date)]

    if valuation.empty:          # keep this one too — the filter can empty it
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
        except Exception as exc:
            # XIRR legitimately fails to converge on some cash-flow shapes; the
            # endpoint still returns (mwr=None), but don't hide why.
            log.warning("XIRR did not converge over %d cash flows: %s", len(flow_dates), exc)
            mwr = None

    start_date = valuation.index[0].date()
    end_date = valuation.index[-1].date()
    benchmark = _benchmark_series(session, start_date, end_date)

    portfolio_cum = (1.0 + returns).cumprod() - 1.0
    portfolio_cum = portfolio_cum.reindex(valuation.index, fill_value=0.0)
    # Look up through plain dicts: .loc on a duplicated index yields a Series
    # rather than a scalar, and float() then fails at request time.
    portfolio_map = portfolio_cum.to_dict()
    benchmark_map = benchmark.to_dict()
    points = [
        PerformancePoint(
            as_of=idx.date(),
            portfolio_cum_return=float(portfolio_map.get(idx, 0.0)),
            benchmark_cum_return=(
                float(benchmark_map[idx]) if idx in benchmark_map else None
            ),
        )
        for idx in valuation.index
    ]

    return PerformanceSummary(twr=twr, mwr=mwr, start_date=start_date, end_date=end_date, points=points)

from collections import defaultdict, deque
from datetime import date

import dbservice_client as dbs
import pandas as pd

from app.db.tables import EOD_PRICES, TRADES
from app.models.position import PnlHistoryPoint, Position, RealizedPnlEntry
from app.services.analytics_common import build_daily_valuation


def _net_positions(session: dbs.Session) -> pd.DataFrame:
    """Net qty and cost numerator per symbol.

    Aggregated in pandas rather than via SQL GROUP BY: trades is a partitioned
    table (by tradedate), and this DB Service version's SQL GROUP BY aggregates
    per-partition rather than globally, so a plain GROUP BY here silently
    returns one row per trade date instead of one row per symbol.
    """
    df = session.query_sql(query=f"SELECT * FROM {TRADES}", return_as="pandas")
    if df.empty:
        return pd.DataFrame(columns=["symbol", "exch", "netqty", "costnumer"])

    df["costvalue"] = df["qty"] * df["price"]
    grouped = df.groupby("symbol").agg(
        exch=("exchange", "last"),
        netqty=("qty", "sum"),
        costnumer=("costvalue", "sum"),
    ).reset_index()
    return grouped[grouped["netqty"].abs() > 1e-9]


def _latest_prices(session: dbs.Session, symbols: list[str]) -> pd.DataFrame:
    """Latest close per symbol, aggregated in pandas for the same partition reason as _net_positions."""
    if not symbols:
        return pd.DataFrame(columns=["symbol", "close"])
    symlist = ",".join(f"'{s}'" for s in symbols)
    df = session.query_sql(
        query=f"SELECT symbol, pxdate, close FROM {EOD_PRICES} WHERE symbol IN ({symlist})",
        return_as="pandas",
    )
    if df.empty:
        return pd.DataFrame(columns=["symbol", "close"])

    df["pxdate"] = pd.to_datetime(df["pxdate"])
    latest = df.sort_values("pxdate").groupby("symbol").last().reset_index()
    return latest[["symbol", "close"]]


def get_positions(session: dbs.Session) -> list[Position]:
    net = _net_positions(session)
    if net.empty:
        return []

    prices = _latest_prices(session, net["symbol"].tolist())
    merged = net.merge(prices, on="symbol", how="left")

    merged["avg_cost"] = merged["costnumer"] / merged["netqty"]
    merged["close"] = merged["close"].fillna(merged["avg_cost"])
    merged["market_value"] = merged["netqty"] * merged["close"]
    merged["unrealized_pnl"] = merged["market_value"] - merged["netqty"] * merged["avg_cost"]

    total_mv = merged["market_value"].sum()
    merged["weight_pct"] = (merged["market_value"] / total_mv * 100.0) if total_mv else 0.0

    return [
        Position(
            symbol=row["symbol"],
            exchange=row.get("exch", ""),
            qty=row["netqty"],
            avg_cost=row["avg_cost"],
            current_price=row["close"],
            market_value=row["market_value"],
            unrealized_pnl=row["unrealized_pnl"],
            weight_pct=row["weight_pct"],
        )
        for _, row in merged.iterrows()
    ]


def compute_fifo_pnl(trades_df: pd.DataFrame) -> tuple[list[RealizedPnlEntry], dict[str, list[tuple[float, float]]]]:
    """FIFO lot matching per symbol. Returns (realized P&L entries, remaining open lots per symbol)."""
    trades = trades_df.copy()
    trades["tradedate"] = pd.to_datetime(trades["tradedate"])
    trades = trades.sort_values("tradedate")

    lots: dict[str, deque] = defaultdict(deque)  # symbol -> deque[(qty, price)]
    realized: list[RealizedPnlEntry] = []

    for _, row in trades.iterrows():
        symbol = row["symbol"]
        qty = float(row["qty"])
        price = float(row["price"])
        trade_date = row["tradedate"].date()

        if qty > 0:
            lots[symbol].append([qty, price])
            continue

        # sell: match oldest lots first
        remaining = -qty
        while remaining > 1e-9 and lots[symbol]:
            lot = lots[symbol][0]
            matched = min(lot[0], remaining)
            realized.append(
                RealizedPnlEntry(
                    symbol=symbol,
                    close_date=trade_date,
                    qty=matched,
                    proceeds=matched * price,
                    cost_basis=matched * lot[1],
                    realized_pnl=matched * (price - lot[1]),
                )
            )
            lot[0] -= matched
            remaining -= matched
            if lot[0] <= 1e-9:
                lots[symbol].popleft()

    open_lots = {sym: [(q, p) for q, p in dq] for sym, dq in lots.items() if dq}
    return realized, open_lots


def get_pnl_history(session: dbs.Session, from_date: date | None = None) -> list[PnlHistoryPoint]:
    trades_df = session.query_sql(query=f"SELECT * FROM {TRADES}", return_as="pandas")
    if trades_df.empty:
        return []

    symbols = ",".join(f"'{s}'" for s in trades_df["symbol"].unique())
    prices_df = session.query_sql(
        query=f"SELECT * FROM {EOD_PRICES} WHERE symbol IN ({symbols})",
        return_as="pandas",
    )
    if prices_df.empty:
        return []

    valuation = build_daily_valuation(trades_df, prices_df)
    realized, _ = compute_fifo_pnl(trades_df)

    realized_by_date = defaultdict(float)
    for entry in realized:
        realized_by_date[pd.Timestamp(entry.close_date)] += entry.realized_pnl
    realized_series = pd.Series(realized_by_date).reindex(valuation.index, fill_value=0.0).cumsum()

    cost_basis = trades_df.copy()
    cost_basis["tradedate"] = pd.to_datetime(cost_basis["tradedate"]).dt.normalize()
    cost_by_day = cost_basis.groupby("tradedate").apply(lambda g: (g["qty"] * g["price"]).sum())
    cost_cum = cost_by_day.reindex(valuation.index, fill_value=0.0).cumsum()

    points = [
        PnlHistoryPoint(
            as_of=idx.date(),
            market_value=row["market_value"],
            unrealized_pnl=row["market_value"] - cost_cum.loc[idx],
            realized_pnl_cum=realized_series.loc[idx],
        )
        for idx, row in valuation.iterrows()
    ]

    if from_date:
        points = [p for p in points if p.as_of >= from_date]
    return points

"""Per-symbol price history and performance statistics.

This looks at a single instrument on its own terms - what the price did over a
window - which is a different question from what your portfolio did. The
portfolio views weight by position and account for cash flows; nothing here
knows about your trades.
"""
from datetime import date

import dbservice_client as dbs
import numpy as np
import pandas as pd

from app.config import settings
from app.db.tables import EOD_PRICES
from app.logging_config import get_logger

log = get_logger(__name__)

TRADING_DAYS = 252


def available_symbols(session: dbs.Session) -> list[str]:
    """Distinct symbols that have price history stored."""
    df = session.query_sql(
        query=f"SELECT DISTINCT symbol FROM {EOD_PRICES}", return_as="pandas"
    )
    if df.empty:
        return []
    return sorted({str(s).upper() for s in df["symbol"]})


def _load_series(
    session: dbs.Session, symbol: str, from_date: date | None, to_date: date | None
) -> pd.DataFrame:
    clauses = [f"symbol = '{symbol.upper()}'"]
    if from_date:
        clauses.append(f"pxdate >= '{from_date.isoformat()}'")
    if to_date:
        clauses.append(f"pxdate <= '{to_date.isoformat()}'")
    df = session.query_sql(
        query=f"SELECT * FROM {EOD_PRICES} WHERE {' AND '.join(clauses)}",
        return_as="pandas",
    )
    if df.empty:
        return df

    df["pxdate"] = pd.to_datetime(df["pxdate"]).dt.normalize()
    # Overlapping re-ingests append rather than replace, so a symbol can hold
    # several rows per day. Keep one, or every statistic below double-counts.
    before = len(df)
    df = df.sort_values("pxdate").drop_duplicates(subset="pxdate", keep="last")
    if len(df) < before:
        log.warning(
            "%s had %d duplicate row(s) - using the last per day", symbol, before - len(df)
        )
    return df.reset_index(drop=True)


def _stats(df: pd.DataFrame) -> dict:
    """Summary statistics for a single symbol's close series."""
    close = df["close"].astype(float)
    returns = close.pct_change().dropna()

    first_close = float(close.iloc[0])
    last_close = float(close.iloc[-1])
    total_return = (last_close / first_close - 1.0) if first_close else 0.0

    span_days = max((df["pxdate"].iloc[-1] - df["pxdate"].iloc[0]).days, 1)
    years = span_days / 365.25
    annualized_return = (
        ((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 and total_return > -1 else 0.0
    )

    std = float(returns.std()) if len(returns) > 1 else 0.0
    annualized_vol = std * np.sqrt(TRADING_DAYS)
    rf_daily = settings.risk_free_rate / TRADING_DAYS
    sharpe = (
        float((returns.mean() - rf_daily) / std * np.sqrt(TRADING_DAYS)) if std else 0.0
    )

    cum = (1.0 + returns).cumprod()
    drawdown = (cum - cum.cummax()) / cum.cummax() if len(cum) else pd.Series(dtype=float)
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0

    return {
        "bars": int(len(df)),
        "first_date": df["pxdate"].iloc[0].date().isoformat(),
        "last_date": df["pxdate"].iloc[-1].date().isoformat(),
        "first_close": first_close,
        "last_close": last_close,
        "high": float(df["high"].astype(float).max()) if "high" in df else float(close.max()),
        "low": float(df["low"].astype(float).min()) if "low" in df else float(close.min()),
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "annualized_volatility": float(annualized_vol),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": max_drawdown,
        "best_day": float(returns.max()) if len(returns) else 0.0,
        "worst_day": float(returns.min()) if len(returns) else 0.0,
        "avg_volume": float(df["volume"].astype(float).mean()) if "volume" in df else 0.0,
    }


def get_symbol_history(
    session: dbs.Session,
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """Price series plus summary statistics for one symbol."""
    df = _load_series(session, symbol, from_date, to_date)
    if df.empty:
        log.info("No stored history for %s in the requested range", symbol)
        return {"symbol": symbol.upper(), "exchange": None, "stats": None, "series": []}

    close = df["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    cum_return = (1.0 + returns).cumprod() - 1.0
    running_peak = (1.0 + cum_return).cummax()
    drawdown = (1.0 + cum_return) / running_peak - 1.0

    series = [
        {
            "pxdate": row.pxdate.date().isoformat(),
            "close": float(row.close),
            "cum_return": float(cum_return.iloc[i]),
            "drawdown": float(drawdown.iloc[i]),
            "volume": int(row.volume) if not pd.isna(row.volume) else 0,
        }
        for i, row in enumerate(df.itertuples())
    ]

    exchange = str(df["exchange"].iloc[-1]) if "exchange" in df else None
    return {
        "symbol": symbol.upper(),
        "exchange": exchange,
        "stats": _stats(df),
        "series": series,
    }

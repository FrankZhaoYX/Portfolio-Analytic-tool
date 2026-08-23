"""Fetch EOD history for explicitly chosen symbols and date ranges.

This is the engine behind the "Add Stock Data" page and POST /api/market-data/fetch.
It differs from market_data_service.refresh_eod_prices in that the caller names
the symbols and the window, rather than them being derived from your trades.

scripts/fetch_history.py implements the same planning rules; it should be slimmed
down to call this module once both files can be edited together.
"""
import uuid
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path

import dbservice_client as dbs
import pandas as pd

from app.config import settings
from app.db.session import INGEST_LOCK, wait_for_import
from app.db.tables import EOD_PRICES
from app.logging_config import get_logger
from app.services import eodhd_client

log = get_logger(__name__)


@dataclass(frozen=True)
class FetchPlan:
    """One symbol's slice of work."""

    symbol: str
    exchange: str
    start: date
    end: date

    @property
    def label(self) -> str:
        return f"{self.symbol}.{self.exchange}"

    @property
    def span_days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        d["label"] = self.label
        d["span_days"] = self.span_days
        return d


def parse_symbol(token: str) -> tuple[str, str]:
    """'AAPL.US' -> ('AAPL', 'US'). A bare ticker defaults to the US exchange."""
    ticker, _, exchange = token.strip().partition(".")
    if not ticker:
        raise ValueError(f"not a symbol: {token!r}")
    return ticker.upper(), (exchange or "US").upper()


def parse_symbols(tokens) -> list[tuple[str, str]]:
    """Parse a list of symbol tokens, dropping blanks and duplicates, order kept."""
    pairs: list[tuple[str, str]] = []
    for token in tokens:
        if not str(token).strip():
            continue
        pair = parse_symbol(str(token))
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def stored_coverage(session: dbs.Session, pairs=None) -> pd.DataFrame:
    """What eod_prices already holds: rows, distinct days, and date span per symbol.

    Aggregated in pandas, not SQL: GROUP BY on a partitioned table aggregates
    per partition on this DB Service version, so a pushed-down MIN/MAX/COUNT
    silently returns one row per partition.
    """
    where = ""
    if pairs:
        symlist = ",".join(f"'{sym}'" for sym, _ in pairs)
        where = f" WHERE symbol IN ({symlist})"
    df = session.query_sql(
        query=f"SELECT symbol, pxdate FROM {EOD_PRICES}{where}", return_as="pandas"
    )
    if df.empty:
        return pd.DataFrame(columns=["symbol", "rows", "days", "first", "last", "duplicates"])

    df["pxdate"] = pd.to_datetime(df["pxdate"]).dt.normalize()
    grouped = df.groupby("symbol")["pxdate"].agg(
        rows="count", days="nunique", first="min", last="max"
    ).reset_index()
    grouped["duplicates"] = grouped["rows"] - grouped["days"]
    grouped["first"] = grouped["first"].dt.date
    grouped["last"] = grouped["last"].dt.date
    return grouped.sort_values("symbol").reset_index(drop=True)


def latest_stored(session: dbs.Session, pairs) -> dict[str, date]:
    """Newest stored pxdate per ticker, for incremental planning."""
    coverage = stored_coverage(session, pairs)
    if coverage.empty:
        return {}
    return {str(r.symbol).upper(): r.last for r in coverage.itertuples()}


def build_plan(pairs, window_start: date, window_end: date, already=None):
    """Decide what to fetch. Returns (plan, skipped-labels).

    With `already` supplied (incremental), each symbol resumes the day after its
    newest stored bar - which also guarantees no overlapping range, and therefore
    no duplicate rows, since the DB Service appends rather than replaces on
    re-ingest of the same dates.
    """
    already = already or {}
    plan: list[FetchPlan] = []
    skipped: list[str] = []

    for ticker, exchange in pairs:
        start = window_start
        have_through = already.get(ticker)
        if have_through is not None:
            start = max(start, have_through + timedelta(days=1))
        if start > window_end:
            skipped.append(f"{ticker}.{exchange}")
            continue
        plan.append(FetchPlan(ticker, exchange, start, window_end))

    return plan, skipped


# EODHD identifies an instrument as TICKER.EXCHANGE. A bare ticker defaults to
# .US here, so anything listed elsewhere comes back empty unless the suffix is
# given. These are the suffixes worth suggesting when a lookup finds nothing.
COMMON_EXCHANGES = {
    "US": "US (NYSE/NASDAQ/AMEX)",
    "TO": "Toronto (TSX)",
    "NEO": "Canada (NEO)",
    "L": "London (LSE)",
    "AS": "Amsterdam",
    "PA": "Paris",
    "F": "Frankfurt",
    "DE": "XETRA",
    "SW": "Swiss",
    "HK": "Hong Kong",
    "AU": "Australia (ASX)",
    "TSE": "Tokyo",
    "INDX": "indices, e.g. GSPC.INDX",
    "FOREX": "FX pairs",
    "CC": "crypto",
}


def no_data_hint(item: "FetchPlan") -> str:
    """Explain an empty result, since EODHD returns 200 with [] rather than erroring."""
    others = ", ".join(
        f"{item.symbol}.{code}" for code in ("TO", "L", "AS", "DE", "HK", "AU") if code != item.exchange
    )
    known = COMMON_EXCHANGES.get(item.exchange)
    where = f"{item.exchange} — {known}" if known else item.exchange
    return (
        f"EODHD returned no bars for {item.label} on exchange {where}. "
        f"The ticker is most likely listed elsewhere: try {others}. "
        "It may also be outside your plan's coverage, or have no trading "
        "in the requested date range."
    )


def rows_from_bars(item: FetchPlan, bars: list[dict]) -> list[dict]:
    """Map EODHD's payload onto the eod_prices schema."""
    return [
        {
            "pxdate": bar["date"],
            "symbol": item.symbol,
            "exchange": item.exchange,
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "close": bar.get("close"),
            "adjclose": bar.get("adjusted_close", bar.get("close")),
            "volume": bar.get("volume", 0),
        }
        for bar in bars
    ]


def run_plan(session: dbs.Session, plan: list[FetchPlan]) -> dict:
    """Fetch every slice, ingest as one file, and report what happened."""
    rows: list[dict] = []
    per_symbol: dict[str, int] = {}
    failed: dict[str, str] = {}
    no_data: dict[str, str] = {}

    for item in plan:
        log.info("Fetching %s  %s -> %s", item.label, item.start, item.end)
        try:
            bars = eodhd_client.get_eod_history(
                item.symbol, item.exchange, item.start, item.end
            )
        except Exception as exc:
            log.warning("  failed: %s", exc)
            failed[item.label] = str(exc)
            continue

        if not bars:
            # EODHD answers 200 with an empty list for a symbol it doesn't carry
            # on this exchange - no exception to catch. Wrong exchange suffix is
            # far and away the usual cause (VDY is .TO, not the .US default).
            hint = no_data_hint(item)
            log.warning("  no data returned for %s - %s", item.label, hint)
            no_data[item.label] = hint
            continue

        mapped = rows_from_bars(item, bars)
        per_symbol[item.label] = len(mapped)
        log.info("  %d bar(s)", len(mapped))
        rows.extend(mapped)

    if not rows:
        log.warning("Nothing fetched - nothing ingested")
        return {
            "ingested": 0,
            "per_symbol": per_symbol,
            "failed": failed,
            "no_data": no_data,
            "partition_days": 0,
        }

    df = pd.DataFrame(rows).drop_duplicates(subset=["symbol", "pxdate"], keep="last")
    imports_dir = Path(settings.db_service_imports_dir)
    imports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"eod_fetch_{uuid.uuid4().hex}.csv"
    df.to_csv(imports_dir / filename, index=False)

    partition_days = int(df["pxdate"].nunique())
    log.info(
        "Wrote %d row(s) to %s, ingesting across ~%d partition-day(s)",
        len(df), filename, partition_days,
    )

    with INGEST_LOCK:
        result = session.import_files(table=EOD_PRICES, path=filename, createTable=False)
        wait_for_import(session, result)

    log.info("Ingested %d row(s) for %d symbol(s)", len(df), df["symbol"].nunique())
    return {
        "ingested": int(len(df)),
        "per_symbol": per_symbol,
        "failed": failed,
        "no_data": no_data,
        "partition_days": partition_days,
    }

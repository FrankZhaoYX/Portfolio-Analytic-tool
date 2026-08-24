"""Fetch EOD price history from EODHD for chosen symbols and a chosen date range.

Unlike `POST /api/market-data/refresh`, which always pulls a fixed trailing
window for everything you hold, this is for targeted backfills: one symbol, one
range, on demand.

Examples
--------
Explicit symbols and range::

    python scripts/fetch_history.py AAPL.US MSFT.US --from 2023-01-01 --to 2024-12-31

Cover everything you actually hold, back to your first trade in that symbol —
this is the one that fixes short-history gaps after entering an old trade::

    python scripts/fetch_history.py --from-trades

Top up only the missing tail, skipping what is already stored::

    python scripts/fetch_history.py --from-trades --incremental

See the plan without touching the database::

    python scripts/fetch_history.py --from-trades --dry-run

Notes
-----
Bare tickers default to the US exchange, so ``AAPL`` and ``AAPL.US`` are the same.
Run with ``backend/.venv`` active, from the repo root.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings  # noqa: E402
from app.db.session import INGEST_LOCK, get_session, wait_for_import  # noqa: E402
from app.db.tables import EOD_PRICES, TRADES  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.services import eodhd_client  # noqa: E402

log = get_logger(__name__)

# Ingest cost is roughly linear in partition-days (one directory written per
# calendar day per table), so warn before a plan that will take many minutes.
LARGE_PLAN_DAYS = 2000


@dataclass(frozen=True)
class Fetch:
    """One symbol's slice of work: what to ask the vendor for."""

    ticker: str
    exchange: str
    start: date
    end: date

    @property
    def label(self) -> str:
        return f"{self.ticker}.{self.exchange}"

    @property
    def span_days(self) -> int:
        return (self.end - self.start).days + 1


# --------------------------------------------------------------------------
# pure helpers - no I/O, so they can be unit tested directly
# --------------------------------------------------------------------------

def parse_symbol(token: str) -> tuple[str, str]:
    """``'AAPL.US'`` -> ``('AAPL', 'US')``. A bare ticker defaults to ``US``."""
    ticker, _, exchange = token.strip().partition(".")
    if not ticker:
        raise argparse.ArgumentTypeError(f"not a symbol: {token!r}")
    return ticker.upper(), (exchange or "US").upper()


def parse_day(token: str) -> date:
    try:
        return datetime.strptime(token.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {token!r}") from None


def build_plan(
    pairs: list[tuple[str, str]],
    window_start: date,
    window_end: date,
    already_have_through: dict[str, date] | None = None,
) -> tuple[list[Fetch], list[str]]:
    """Decide what to fetch per symbol.

    `already_have_through` maps ticker -> newest stored pxdate; when supplied
    (incremental mode) each symbol starts the day after what is already stored,
    which also means re-ingesting an overlapping range can't duplicate rows.

    Returns (work to do, labels skipped because they are already current).
    """
    already_have_through = already_have_through or {}
    plan: list[Fetch] = []
    skipped: list[str] = []

    for ticker, exchange in pairs:
        start = window_start
        have_through = already_have_through.get(ticker)
        if have_through is not None:
            start = max(start, have_through + timedelta(days=1))
        if start > window_end:
            skipped.append(f"{ticker}.{exchange}")
            continue
        plan.append(Fetch(ticker, exchange, start, window_end))

    return plan, skipped


def rows_from_bars(fetch: Fetch, bars: list[dict]) -> list[dict]:
    """Map EODHD's payload onto the eod_prices schema."""
    return [
        {
            "pxdate": bar["date"],
            "symbol": fetch.ticker,
            "exchange": fetch.exchange,
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "close": bar.get("close"),
            "adjclose": bar.get("adjusted_close", bar.get("close")),
            "volume": bar.get("volume", 0),
        }
        for bar in bars
    ]


# --------------------------------------------------------------------------
# database reads
# --------------------------------------------------------------------------
# Aggregates (MIN / MAX / GROUP BY) are deliberately NOT pushed into the query:
# on this DB Service version they evaluate per partition rather than globally,
# so a pushed-down MAX returns one row per partition. Pull the column, reduce
# in pandas. See the architecture notes, section 5.

def symbols_from_trades(session) -> list[tuple[str, str]]:
    df = session.query_sql(
        query=f"SELECT DISTINCT symbol, exchange FROM {TRADES}", return_as="pandas"
    )
    if df.empty:
        return []
    pairs = {(str(s).upper(), str(e).upper()) for s, e in zip(df["symbol"], df["exchange"])}
    return sorted(pairs)


def first_trade_dates(session) -> dict[str, date]:
    """Earliest tradedate per ticker, so history can start where the position did."""
    df = session.query_sql(
        query=f"SELECT symbol, tradedate FROM {TRADES}", return_as="pandas"
    )
    if df.empty:
        return {}
    df["tradedate"] = pd.to_datetime(df["tradedate"])
    return {
        str(sym).upper(): stamp.date()
        for sym, stamp in df.groupby("symbol")["tradedate"].min().items()
    }


def latest_price_dates(session, pairs: list[tuple[str, str]]) -> dict[str, date]:
    """Newest pxdate already stored, per ticker."""
    if not pairs:
        return {}
    symlist = ",".join(f"'{ticker}'" for ticker, _ in pairs)
    df = session.query_sql(
        query=f"SELECT symbol, pxdate FROM {EOD_PRICES} WHERE symbol IN ({symlist})",
        return_as="pandas",
    )
    if df.empty:
        return {}
    df["pxdate"] = pd.to_datetime(df["pxdate"])
    return {
        str(sym).upper(): stamp.date()
        for sym, stamp in df.groupby("symbol")["pxdate"].max().items()
    }


# --------------------------------------------------------------------------
# fetch + ingest
# --------------------------------------------------------------------------

def run_plan(session, plan: list[Fetch]) -> int:
    """Fetch every slice, then ingest the lot as one file. Returns rows ingested."""
    rows: list[dict] = []
    failed: list[str] = []

    for fetch in plan:
        log.info("Fetching %s  %s -> %s", fetch.label, fetch.start, fetch.end)
        try:
            bars = eodhd_client.get_eod_history(
                fetch.ticker, fetch.exchange, fetch.start, fetch.end
            )
        except Exception as exc:
            log.warning("  failed: %s", exc)
            failed.append(fetch.label)
            continue
        mapped = rows_from_bars(fetch, bars)
        log.info("  %d bar(s)", len(mapped))
        rows.extend(mapped)

    if failed:
        log.warning("Skipped %d symbol(s) after errors: %s", len(failed), ", ".join(failed))
    if not rows:
        log.warning("Nothing fetched - nothing ingested")
        return 0

    df = pd.DataFrame(rows).drop_duplicates(subset=["symbol", "pxdate"], keep="last")
    imports_dir = Path(settings.db_service_imports_dir)
    imports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"eod_backfill_{uuid.uuid4().hex}.csv"
    df.to_csv(imports_dir / filename, index=False)
    log.info("Wrote %d row(s) to %s", len(df), filename)

    partition_days = df["pxdate"].nunique()
    log.info("Ingesting across ~%d partition-day(s) - this is the slow part", partition_days)

    with INGEST_LOCK:
        result = session.import_files(table=EOD_PRICES, path=filename, createTable=False)
        wait_for_import(session, result)

    log.info("Ingested %d row(s) for %d symbol(s)", len(df), df["symbol"].nunique())
    return len(df)


def describe_plan(plan: list[Fetch], skipped: list[str]) -> None:
    if skipped:
        log.info("Already current, skipping: %s", ", ".join(skipped))
    if not plan:
        log.info("Nothing to fetch")
        return
    log.info("Plan - %d symbol(s):", len(plan))
    for fetch in plan:
        log.info("  %-12s %s -> %s  (%d day span)", fetch.label, fetch.start, fetch.end, fetch.span_days)
    total = sum(f.span_days for f in plan)
    if total > LARGE_PLAN_DAYS:
        log.warning(
            "Large plan (~%d symbol-days). Ingest is roughly one partition-day at a "
            "time, so expect several minutes.",
            total,
        )


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_history.py",
        description="Backfill EOD price history from EODHD for specific symbols and dates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  fetch_history.py AAPL.US --from 2023-01-01\n"
            "  fetch_history.py AAPL.US MSFT.US --from 2020-01-01 --to 2023-12-31\n"
            "  fetch_history.py --from-trades                # everything held, from first trade\n"
            "  fetch_history.py --from-trades --incremental  # only the missing tail\n"
        ),
    )
    parser.add_argument(
        "symbols", nargs="*", type=parse_symbol, metavar="SYMBOL",
        help="TICKER.EXCHANGE, e.g. AAPL.US. Bare ticker assumes .US",
    )
    parser.add_argument(
        "--from", dest="from_date", type=parse_day, metavar="YYYY-MM-DD",
        help="start of range (default: one year back, or first trade with --from-trades)",
    )
    parser.add_argument(
        "--to", dest="to_date", type=parse_day, metavar="YYYY-MM-DD",
        help="end of range (default: today)",
    )
    parser.add_argument(
        "--from-trades", action="store_true",
        help="derive symbols from your trades, each starting at its own first trade date",
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help="skip dates already stored; start each symbol after its newest stored bar",
    )
    parser.add_argument(
        "--no-benchmark", action="store_true",
        help=f"exclude the configured benchmark ({settings.benchmark_symbol})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the plan and exit without fetching or ingesting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.symbols and not args.from_trades:
        log.error("Give at least one SYMBOL, or use --from-trades. See --help.")
        return 2

    session = get_session()
    to_date = args.to_date or date.today()

    pairs: list[tuple[str, str]] = list(args.symbols)
    per_symbol_start: dict[str, date] = {}

    if args.from_trades:
        held = symbols_from_trades(session)
        if not held:
            log.error("No trades recorded, so there is nothing to derive symbols from")
            return 1
        log.info("From trades: %s", ", ".join(f"{t}.{e}" for t, e in held))
        for pair in held:
            if pair not in pairs:
                pairs.append(pair)
        if args.from_date is None:
            # Each symbol only needs history back to when you first held it.
            per_symbol_start = first_trade_dates(session)

    if not args.no_benchmark:
        bench = parse_symbol(settings.benchmark_symbol)
        if bench not in pairs:
            pairs.append(bench)
            log.info("Including benchmark %s.%s", *bench)

    default_start = args.from_date or (to_date - timedelta(days=365))
    already = latest_price_dates(session, pairs) if args.incremental else {}

    plan: list[Fetch] = []
    skipped: list[str] = []
    for ticker, exchange in pairs:
        window_start = per_symbol_start.get(ticker, default_start)
        if window_start > to_date:
            log.warning(
                "%s.%s first traded %s, after --to %s - skipping",
                ticker, exchange, window_start, to_date,
            )
            continue
        one, one_skipped = build_plan([(ticker, exchange)], window_start, to_date, already)
        plan.extend(one)
        skipped.extend(one_skipped)

    describe_plan(plan, skipped)

    if args.dry_run:
        log.info("Dry run - stopping before fetch")
        return 0
    if not plan:
        return 0

    run_plan(session, plan)
    return 0


if __name__ == "__main__":
    setup_logging(log_file="ingest.log")
    raise SystemExit(main())

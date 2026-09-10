"""Standalone CLI to ingest a defined backtest universe into `eod_prices`.

`ingest_eodhd_eod.py` refreshes only the symbols you hold, because it derives
them from recorded trades. A backtest needs a universe that exists independent
of your positions -- index constituents, ETFs, ETPs -- so this reads that
universe from `data/universe/*.csv` and feeds it through the same table.

Usage (from the repo root):
    python scripts/ingest_backtest_universe.py --resolve      # refresh constituent lists
    python scripts/ingest_backtest_universe.py --fetch        # populate the local cache
    python scripts/ingest_backtest_universe.py --ingest       # cache -> eod_prices
    python scripts/ingest_backtest_universe.py --fetch --ingest --universe sp500,etf_us

WHY THE UNIVERSE IS A FILE
--------------------------
Backtesting against *today's* index membership is survivorship bias: the
companies that dropped out of the S&P 500 are the ones that did badly, so a
universe of current members flatters every strategy tested against it. Keeping
the universe in a checked-in file does not fix that -- it makes it explicit and
the run reproducible. Point-in-time membership is the real fix and needs a
historical-constituents feed.

WHY FETCH AND INGEST ARE SEPARATE
---------------------------------
`market_data_service.refresh_eod_prices` fetches and ingests in one pass, which
is right for the handful of symbols you hold. It does not scale to a universe,
for two reasons that pull in opposite directions:

  - EODHD is one HTTP call per symbol per call, so fetching must be done once
    per symbol over the whole date range. Re-fetching per time slice would
    multiply a 600-call run into a 12,000-call one against a metered plan.
  - `eod_prices` is partitioned by `pxdate`, so ingesting must be done in date
    slices. Feeding it symbol-by-symbol rewrites every date partition once per
    batch -- the same partitions, over and over.

Doing both in one pass forces you to pick which one to do badly. So this
fetches each symbol once into `data/raw/eodhd/`, then ingests out of that cache
in date chunks: 600 calls, and each partition written once. The cache also
makes an interrupted run resumable, which matters when the fetch is the slow
half and the ingest is the fragile one.
"""
import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import INGEST_LOCK, get_session, wait_for_import  # noqa: E402
from app.db.tables import EOD_PRICES  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.services import eodhd_client  # noqa: E402

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_DIR = REPO_ROOT / "data" / "universe"
CACHE_DIR = REPO_ROOT / "data" / "raw" / "eodhd"

# EODHD index code -> (universe file, exchange, asset kind) it populates.
INDEX_SOURCES = {
    "sp500": (("GSPC", "INDX"), "US", "stock"),
    "nasdaq100": (("NDX", "INDX"), "US", "stock"),
    "tsx60": (("GSPTSE", "INDX"), "TO", "stock"),
}


def resolve(names: list[str]) -> None:
    """Rewrite data/universe/<name>.csv from EODHD index constituents.

    Needs the fundamentals entitlement. On an EOD-only plan this returns 403 --
    populate the files by hand instead, with the same four columns. That is the
    reproducible path regardless.
    """
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        if name not in INDEX_SOURCES:
            log.info("No index mapping for %r - skipping (edit it by hand)", name)
            continue
        (code, idx_exch), exchange, kind = INDEX_SOURCES[name]
        try:
            data = eodhd_client.get_fundamentals(code, idx_exch)
        except Exception as exc:
            log.warning("Constituent fetch failed for %s (%s.%s): %s -- "
                        "populate data/universe/%s.csv by hand",
                        name, code, idx_exch, exc, name)
            continue
        components = (data or {}).get("Components") or {}
        rows = []
        for comp in components.values():
            sym = (comp.get("Code") or "").strip().upper()
            if sym:
                # Commas break naive CSV consumers downstream; names are only
                # a human label here so stripping them costs nothing.
                rows.append((sym, exchange, kind,
                             (comp.get("Name") or "").replace(",", " ").strip()))
        if not rows:
            log.warning("No Components in the response for %s - leaving %s.csv alone",
                        name, name)
            continue
        out = UNIVERSE_DIR / f"{name}.csv"
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["sym", "exch", "kind", "note"])
            writer.writerows(sorted(rows))
        log.info("Wrote %d constituents to %s", len(rows), out.relative_to(REPO_ROOT))


def read_universe(names: list[str]) -> list[tuple[str, str]]:
    """Union of the named universe files as (symbol, exchange) pairs.

    De-duplicates across files -- a ticker can legitimately sit in two lists
    (GLD is both a popular ETF and a commodity trust). Note this only protects
    a *single* invocation: ingesting etf_us in one run and etp_us in another
    double-ingests anything they share, because nothing here can see the rows
    the earlier run already wrote. Ingest overlapping universes together.
    """
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    overlaps: list[str] = []
    for name in names:
        path = UNIVERSE_DIR / f"{name}.csv"
        if not path.is_file():
            log.warning("Missing %s - skipped (run --resolve, or create it by hand)",
                        path.relative_to(REPO_ROOT))
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            count = dupe = 0
            for row in csv.DictReader(fh):
                sym = (row.get("sym") or "").strip().upper()
                exch = (row.get("exch") or "US").strip().upper()
                if not sym:
                    continue
                if (sym, exch) in seen:
                    dupe += 1
                    overlaps.append(f"{sym}.{exch} ({name})")
                    continue
                seen.add((sym, exch))
                pairs.append((sym, exch))
                count += 1
        log.info("%s: %d symbols%s", path.name, count,
                 f" ({dupe} already seen in an earlier file)" if dupe else "")
    if overlaps:
        log.info("De-duplicated across universe files: %s", ", ".join(overlaps))
    return pairs


def _cache_path(symbol: str, exchange: str) -> Path:
    return CACHE_DIR / f"{symbol.upper()}.{exchange.upper()}.json"


def _cache_covers(path: Path, from_date: date, to_date: date) -> bool:
    """True if the cached file already spans the requested window.

    Presence alone is not enough. A cache fetched for 2024-2026 does not
    satisfy a later 10-year request, and reusing it would silently give that
    symbol a shorter history than the rest of the universe -- a gap that looks
    like "this ticker listed late" rather than a caching bug.
    """
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
        return (date.fromisoformat(blob["from"]) <= from_date
                and date.fromisoformat(blob["to"]) >= to_date)
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return False  # unreadable or pre-dates the range metadata - re-fetch


def fetch(pairs: list[tuple[str, str]], from_date: date, to_date: date,
          refresh: bool = False) -> int:
    """Fetch each symbol's full history once into data/raw/eodhd/.

    Skips symbols whose cache already covers the requested window unless
    `refresh`, so re-running after an interruption costs nothing. One bad
    ticker is logged and skipped rather than sinking the run -- with several
    hundred symbols, a few delisted or renamed tickers are expected, not
    exceptional.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fetched = cached = failed = 0

    for n, (symbol, exchange) in enumerate(pairs, 1):
        path = _cache_path(symbol, exchange)
        if path.is_file() and not refresh and _cache_covers(path, from_date, to_date):
            cached += 1
            continue
        try:
            history = eodhd_client.get_eod_history(symbol, exchange, from_date, to_date)
        except Exception as exc:
            log.warning("[%d/%d] fetch failed for %s.%s: %s", n, len(pairs),
                        symbol, exchange, exc)
            failed += 1
            continue
        # Record the range alongside the bars: a cache file gives no other way
        # to tell "no data in this window" apart from "fetched a shorter window".
        path.write_text(json.dumps({
            "symbol": symbol.upper(), "exchange": exchange.upper(),
            "from": from_date.isoformat(), "to": to_date.isoformat(),
            "bars": history,
        }), encoding="utf-8")
        fetched += 1
        if n % 25 == 0 or n == len(pairs):
            log.info("Fetch progress %d/%d (new %d, cached %d, failed %d)",
                     n, len(pairs), fetched, cached, failed)

    log.info("Fetch done: %d new, %d already cached, %d failed", fetched, cached, failed)
    return fetched


def load_cached(pairs: list[tuple[str, str]]) -> pd.DataFrame:
    """Build one frame from the cache, in the column shape `eod_prices` expects."""
    rows: list[dict] = []
    missing = 0
    for symbol, exchange in pairs:
        path = _cache_path(symbol, exchange)
        if not path.is_file():
            missing += 1
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A truncated cache file (interrupted write) should be re-fetched,
            # not silently treated as an empty history.
            log.warning("Unreadable cache %s: %s - re-run --fetch --refresh-cache",
                        path.name, exc)
            missing += 1
            continue
        for bar in blob.get("bars") or []:
            rows.append({
                "pxdate": bar["date"],
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "adjclose": bar.get("adjusted_close", bar.get("close")),
                "volume": bar.get("volume", 0),
            })
    if missing:
        log.warning("%d symbol(s) had no usable cache - run --fetch first", missing)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    log.info("Loaded %d row(s) from cache across %d symbol(s)",
             len(df), df["symbol"].nunique())
    return df


def _add_months(d: date, months: int) -> date:
    """Same day-of-month `months` later, clamped to the target month's length."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    # Day 31 has no counterpart in a 30-day month; step back to that month's end.
    for day in range(d.day, 0, -1):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(f"could not shift {d} by {months} months")


def date_chunks(from_date: date, to_date: date, months: int):
    """Half-open-ish inclusive [start, end] windows covering the range."""
    cur = from_date
    while cur <= to_date:
        end = _add_months(cur, months) - timedelta(days=1)
        yield cur, min(end, to_date)
        cur = end + timedelta(days=1)


def ingest(df: pd.DataFrame, from_date: date, to_date: date, chunk_months: int) -> int:
    """Ingest in date chunks, so each `pxdate` partition is written exactly once."""
    if df.empty:
        log.warning("Nothing to ingest - the cache produced no rows")
        return 0

    session = get_session()
    imports_dir = Path(settings.db_service_imports_dir)
    imports_dir.mkdir(parents=True, exist_ok=True)

    # Parse once for slicing; the CSV keeps the original ISO strings, which is
    # the form the DB Service already accepts from refresh_eod_prices.
    when = pd.to_datetime(df["pxdate"], errors="coerce")
    if when.isna().any():
        bad = int(when.isna().sum())
        log.warning("Dropping %d row(s) with an unparseable pxdate", bad)
        df, when = df[when.notna()], when[when.notna()]

    chunks = list(date_chunks(from_date, to_date, chunk_months))
    log.info("Ingesting %d row(s) in %d chunk(s) of %d month(s), %s to %s",
             len(df), len(chunks), chunk_months, from_date, to_date)

    total = 0
    for n, (start, end) in enumerate(chunks, 1):
        mask = (when >= pd.Timestamp(start)) & (when <= pd.Timestamp(end))
        part = df[mask]
        if part.empty:
            log.info("Chunk %d/%d %s..%s: no rows, skipped", n, len(chunks), start, end)
            continue

        filename = f"eod_prices_{start:%Y%m%d}_{end:%Y%m%d}.csv"
        part.to_csv(imports_dir / filename, index=False)
        try:
            # Serialised deliberately: concurrent ingests corrupt partitions,
            # which is what INGEST_LOCK exists to prevent.
            with INGEST_LOCK:
                result = session.import_files(
                    table=EOD_PRICES, path=filename, createTable=False
                )
                wait_for_import(session, result)
        except Exception as exc:
            # Keep going: a failed chunk is recoverable by re-running that date
            # range, and stopping here would waste the chunks already landed.
            log.error("Chunk %d/%d %s..%s failed (%d rows): %s",
                      n, len(chunks), start, end, len(part), exc)
            continue
        total += len(part)
        log.info("Chunk %d/%d %s..%s ingested %d row(s), running total %d",
                 n, len(chunks), start, end, len(part), total)
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resolve", action="store_true",
                    help="rebuild data/universe/*.csv from EODHD index constituents")
    ap.add_argument("--fetch", action="store_true",
                    help="fetch EOD history into data/raw/eodhd/ (one call per symbol)")
    ap.add_argument("--ingest", action="store_true",
                    help="ingest the cached history into eod_prices, in date chunks")
    ap.add_argument("--refresh-cache", action="store_true",
                    help="with --fetch, re-download symbols that are already cached")
    ap.add_argument("--universe", default="sp500,nasdaq100,etf_us",
                    help="comma-separated universe files (default: %(default)s)")
    ap.add_argument("--from", dest="from_date", default="2015-01-01",
                    help="earliest bar date (default: %(default)s)")
    ap.add_argument("--to", dest="to_date", default=None,
                    help="latest bar date (default: today)")
    ap.add_argument("--chunk-months", type=int, default=12,
                    help="months of data per ingest job (default: %(default)s)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap the number of symbols, for a smoke test")
    args = ap.parse_args()

    if not (args.resolve or args.fetch or args.ingest):
        ap.error("pick at least one of --resolve / --fetch / --ingest")

    names = [n.strip() for n in args.universe.split(",") if n.strip()]

    if args.resolve:
        resolve(names)

    if not (args.fetch or args.ingest):
        return

    pairs = read_universe(names)
    if args.limit:
        pairs = pairs[: args.limit]
    if not pairs:
        log.warning("Universe is empty - nothing to do. Populate "
                    "data/universe/*.csv first.")
        return

    from_date = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    to_date = (datetime.strptime(args.to_date, "%Y-%m-%d").date()
               if args.to_date else date.today())

    if args.fetch:
        fetch(pairs, from_date, to_date, refresh=args.refresh_cache)

    if args.ingest:
        total = ingest(load_cached(pairs), from_date, to_date, args.chunk_months)
        log.info("Done: %d row(s) ingested into eod_prices across %d symbol(s)",
                 total, len(pairs))


if __name__ == "__main__":
    setup_logging(log_file="ingest_backtest_universe.log")
    main()

import uuid
from datetime import date, timedelta
from pathlib import Path

import dbservice_client as dbs
import pandas as pd

from app.config import settings
from app.db.session import INGEST_LOCK, wait_for_import
from app.db.tables import EOD_PRICES, FUNDAMENTALS, QUOTES, TRADES
from app.logging_config import get_logger
from app.services import eodhd_client
from app.timeutil import utc_now_iso

log = get_logger(__name__)


def get_portfolio_symbols(session: dbs.Session) -> list[tuple[str, str]]:
    """Distinct (symbol, exchange) pairs from trades, plus the configured benchmark."""
    df = session.query_sql(query=f"SELECT DISTINCT symbol, exchange FROM {TRADES}", return_as="pandas")
    pairs = list(zip(df["symbol"], df["exchange"])) if not df.empty else []

    bench_symbol, _, bench_exchange = settings.benchmark_symbol.partition(".")
    if (bench_symbol, bench_exchange) not in pairs:
        pairs.append((bench_symbol, bench_exchange or "INDX"))
    return pairs


def refresh_eod_prices(
    session: dbs.Session,
    pairs: list[tuple[str, str]],
    from_date: date | None = None,
    to_date: date | None = None,
) -> int:
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=365))

    log.info(
        "Refreshing EOD prices for %d symbol(s) from %s to %s", len(pairs), from_date, to_date
    )
    rows: list[dict] = []
    failed: list[str] = []
    for symbol, exchange in pairs:
        try:
            history = eodhd_client.get_eod_history(symbol, exchange, from_date, to_date)
        except Exception as exc:
            # One bad ticker shouldn't sink the whole refresh, but it must be
            # visible - a silent skip here looks identical to "no data exists".
            log.warning("EOD fetch failed for %s.%s: %s", symbol, exchange, exc)
            failed.append(f"{symbol}.{exchange}")
            continue
        log.debug("Fetched %d EOD bars for %s.%s", len(history), symbol, exchange)
        for bar in history:
            rows.append(
                {
                    "pxdate": bar["date"],
                    "symbol": symbol.upper(),
                    "exchange": exchange.upper(),
                    "open": bar.get("open"),
                    "high": bar.get("high"),
                    "low": bar.get("low"),
                    "close": bar.get("close"),
                    "adjclose": bar.get("adjusted_close", bar.get("close")),
                    "volume": bar.get("volume", 0),
                }
            )

    if failed:
        log.warning("EOD refresh skipped %d symbol(s): %s", len(failed), ", ".join(failed))
    if not rows:
        log.warning("EOD refresh produced no rows - nothing ingested")
        return 0

    df = pd.DataFrame(rows)
    imports_dir = Path(settings.db_service_imports_dir)
    filename = f"eod_prices_{uuid.uuid4().hex}.csv"
    df.to_csv(imports_dir / filename, index=False)
    log.info("Wrote %d EOD rows to %s, starting ingest", len(df), filename)

    with INGEST_LOCK:
        result = session.import_files(table=EOD_PRICES, path=filename, createTable=False)
        wait_for_import(session, result)
    log.info("Ingested %d EOD price rows", len(df))
    return len(df)


def refresh_quotes(session: dbs.Session, pairs: list[tuple[str, str]]) -> int:
    symbols = [f"{s.upper()}.{e.upper()}" for s, e in pairs]
    log.info("Refreshing quotes for %d symbol(s)", len(symbols))
    try:
        quotes = eodhd_client.get_real_time_quotes(symbols)
    except Exception as exc:
        log.warning("Quote fetch failed for %s: %s", ", ".join(symbols), exc)
        return 0
    if not quotes:
        log.warning("Quote refresh returned no data - nothing ingested")
        return 0

    now = utc_now_iso()
    records = [
        {
            "ts": now,
            "symbol": q["code"].split(".")[0].upper(),
            "price": q.get("close", q.get("price")),
            "change": q.get("change", 0.0),
            "changepct": q.get("change_p", 0.0),
            "volume": q.get("volume", 0),
        }
        for q in quotes
        if "code" in q
    ]
    if not records:
        log.warning("Quote refresh produced no usable records - nothing ingested")
        return 0

    with INGEST_LOCK:
        result = session.import_data(table=QUOTES, data=records, insert_as="objects")
        wait_for_import(session, result)
    log.info("Ingested %d quote record(s)", len(records))
    return len(records)


def refresh_fundamentals(session: dbs.Session, pairs: list[tuple[str, str]]) -> int:
    log.info("Refreshing fundamentals for %d symbol(s)", len(pairs))
    today = date.today().isoformat()
    records = []
    failed: list[str] = []
    for symbol, exchange in pairs:
        try:
            data = eodhd_client.get_fundamentals(symbol, exchange)
        except Exception as exc:
            # Was a bare `continue`, which made a bad API key or a rate limit
            # indistinguishable from a symbol genuinely having no fundamentals.
            log.warning("Fundamentals fetch failed for %s.%s: %s", symbol, exchange, exc)
            failed.append(f"{symbol}.{exchange}")
            continue

        general = data.get("General", {})
        highlights = data.get("Highlights", {})
        records.append(
            {
                "asofdate": today,
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "name": general.get("Name", symbol),
                "sector": general.get("Sector", "Unknown"),
                "industry": general.get("Industry", "Unknown"),
                "country": general.get("CountryName", "Unknown"),
                "currency": general.get("CurrencyCode", "USD"),
                "assettype": general.get("Type", "Unknown"),
                "marketcap": highlights.get("MarketCapitalization", 0.0) or 0.0,
            }
        )

    if failed:
        log.warning(
            "Fundamentals refresh skipped %d symbol(s): %s", len(failed), ", ".join(failed)
        )
    if not records:
        log.warning("Fundamentals refresh produced no records - nothing ingested")
        return 0

    with INGEST_LOCK:
        result = session.import_data(table=FUNDAMENTALS, data=records, insert_as="objects")
        wait_for_import(session, result)
    log.info("Ingested %d fundamentals record(s)", len(records))
    return len(records)

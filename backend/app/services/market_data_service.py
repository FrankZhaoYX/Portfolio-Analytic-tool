import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dbservice_client as dbs
import pandas as pd

from app.config import settings
from app.db.session import INGEST_LOCK, wait_for_import
from app.db.tables import EOD_PRICES, FUNDAMENTALS, QUOTES, TRADES
from app.services import eodhd_client


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

    rows: list[dict] = []
    for symbol, exchange in pairs:
        history = eodhd_client.get_eod_history(symbol, exchange, from_date, to_date)
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

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    imports_dir = Path(settings.db_service_imports_dir)
    filename = f"eod_prices_{uuid.uuid4().hex}.csv"
    df.to_csv(imports_dir / filename, index=False)

    with INGEST_LOCK:
        result = session.import_files(table=EOD_PRICES, path=filename, createTable=False)
        wait_for_import(session, result)
    return len(df)


def refresh_quotes(session: dbs.Session, pairs: list[tuple[str, str]]) -> int:
    symbols = [f"{s.upper()}.{e.upper()}" for s, e in pairs]
    quotes = eodhd_client.get_real_time_quotes(symbols)
    if not quotes:
        return 0

    now = datetime.now(timezone.utc).isoformat()
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
        return 0

    with INGEST_LOCK:
        result = session.import_data(table=QUOTES, data=records, insert_as="objects")
        wait_for_import(session, result)
    return len(records)


def refresh_fundamentals(session: dbs.Session, pairs: list[tuple[str, str]]) -> int:
    today = date.today().isoformat()
    records = []
    for symbol, exchange in pairs:
        try:
            data = eodhd_client.get_fundamentals(symbol, exchange)
        except Exception:
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

    if not records:
        return 0

    with INGEST_LOCK:
        result = session.import_data(table=FUNDAMENTALS, data=records, insert_as="objects")
        wait_for_import(session, result)
    return len(records)

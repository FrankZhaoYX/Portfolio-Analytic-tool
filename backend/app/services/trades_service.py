import uuid
from pathlib import Path

import dbservice_client as dbs
import pandas as pd

from app.config import settings
from app.db.session import INGEST_LOCK, wait_for_import
from app.db.tables import TRADES
from app.logging_config import get_logger
from app.models.trade import Side, TradeIn
from app.timeutil import utc_now_iso

log = get_logger(__name__)

REQUIRED_CSV_COLUMNS = {"symbol", "exchange", "side", "qty", "price", "tradedate"}


def _signed_qty(side: Side, qty: float) -> float:
    return qty if side == Side.BUY else -qty


def insert_trade(session: dbs.Session, trade: TradeIn) -> dict:
    record = {
        "tradeid": str(uuid.uuid4()),
        "tradedate": trade.tradedate.isoformat(),
        "symbol": trade.symbol.upper(),
        "exchange": trade.exchange.upper(),
        "side": trade.side.value,
        "qty": _signed_qty(trade.side, trade.qty),
        "price": trade.price,
        "fees": trade.fees,
        "currency": trade.currency.upper(),
        "notes": trade.notes,
        "createdat": utc_now_iso(),
    }
    log.info(
        "Recording trade %s %s %s x%.4f @ %.4f",
        record["tradeid"][:8],
        record["side"],
        record["symbol"],
        abs(record["qty"]),
        record["price"],
    )
    with INGEST_LOCK:
        result = session.import_data(table=TRADES, data=[record], insert_as="objects")
        wait_for_import(session, result)
    return record


def insert_trades_csv(session: dbs.Session, df: pd.DataFrame) -> int:
    missing = REQUIRED_CSV_COLUMNS - set(df.columns.str.lower())
    if missing:
        log.warning("Rejected trade CSV, missing columns: %s", sorted(missing))
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    df = df.rename(columns=str.lower)
    df["side"] = df["side"].str.upper()
    df["qty"] = df.apply(lambda r: _signed_qty(Side(r["side"]), float(r["qty"])), axis=1)
    df["symbol"] = df["symbol"].str.upper()
    df["exchange"] = df["exchange"].str.upper()
    df["currency"] = df.get("currency", "USD")
    df["currency"] = df["currency"].fillna("USD").str.upper()
    df["fees"] = df.get("fees", 0.0)
    df["fees"] = df["fees"].fillna(0.0)
    df["notes"] = df.get("notes", "")
    df["notes"] = df["notes"].fillna("")
    df["tradeid"] = [str(uuid.uuid4()) for _ in range(len(df))]
    df["createdat"] = utc_now_iso()

    cols = ["tradeid", "tradedate", "symbol", "exchange", "side", "qty", "price", "fees", "currency", "notes", "createdat"]
    df = df[cols]

    imports_dir = Path(settings.db_service_imports_dir)
    filename = f"trades_upload_{uuid.uuid4().hex}.csv"
    df.to_csv(imports_dir / filename, index=False)
    log.info("Wrote %d uploaded trade(s) to %s, starting ingest", len(df), filename)

    with INGEST_LOCK:
        result = session.import_files(table=TRADES, path=filename, createTable=False)
        wait_for_import(session, result)
    log.info("Ingested %d trade(s) from upload", len(df))
    return len(df)


def list_trades(session: dbs.Session, limit: int = 200) -> pd.DataFrame:
    return session.query_sql(
        query=f"SELECT * FROM {TRADES} ORDER BY tradedate DESC LIMIT {limit}",
        return_as="pandas",
    )

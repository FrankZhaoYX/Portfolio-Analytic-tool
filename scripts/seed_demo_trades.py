"""POST a small, hand-computable set of demo trades to the running FastAPI backend.

Usage:
    python scripts/seed_demo_trades.py
"""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.logging_config import get_logger, setup_logging  # noqa: E402

log = get_logger(__name__)

BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")

# Generous: each POST waits on a DB Service ingest, which is slow on the
# partitioned tables and can stall outright if the service needs a reset.
REQUEST_TIMEOUT = 120

DEMO_TRADES = [
    {
        "symbol": "AAPL",
        "exchange": "US",
        "side": "BUY",
        "qty": 10,
        "price": 150.0,
        "tradedate": "2025-01-15T00:00:00",
        "fees": 1.0,
        "currency": "USD",
        "notes": "seed",
    },
    {
        "symbol": "MSFT",
        "exchange": "US",
        "side": "BUY",
        "qty": 5,
        "price": 300.0,
        "tradedate": "2025-02-01T00:00:00",
        "fees": 1.0,
        "currency": "USD",
        "notes": "seed",
    },
    {
        "symbol": "AAPL",
        "exchange": "US",
        "side": "SELL",
        "qty": 3,
        "price": 180.0,
        "tradedate": "2025-06-01T00:00:00",
        "fees": 1.0,
        "currency": "USD",
        "notes": "seed",
    },
]


def main() -> None:
    log.info("Seeding %d demo trade(s) via %s", len(DEMO_TRADES), BASE_URL)
    for i, trade in enumerate(DEMO_TRADES, start=1):
        label = f"{trade['side']} {trade['qty']} {trade['symbol']} @ {trade['price']}"
        try:
            resp = requests.post(
                f"{BASE_URL}/api/trades", json=trade, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.Timeout:
            log.error(
                "Trade %d/%d (%s) timed out after %ds. The backend is likely blocked on "
                "a stalled DB Service ingest - check logs/backend.log and the "
                "wait_for_import warnings there.",
                i,
                len(DEMO_TRADES),
                label,
                REQUEST_TIMEOUT,
            )
            raise
        except requests.RequestException as exc:
            log.error("Trade %d/%d (%s) failed: %s", i, len(DEMO_TRADES), label, exc)
            raise
        log.info("Inserted %d/%d: %s", i, len(DEMO_TRADES), label)
    log.info("Seeding complete")


if __name__ == "__main__":
    setup_logging(log_file="scripts.log")
    main()

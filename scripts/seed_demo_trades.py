"""POST a small, hand-computable set of demo trades to the running FastAPI backend.

Usage:
    python scripts/seed_demo_trades.py
"""
import os

import requests

BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")

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
    for trade in DEMO_TRADES:
        resp = requests.post(f"{BASE_URL}/api/trades", json=trade, timeout=30)
        resp.raise_for_status()
        print(f"Inserted: {resp.json()}")


if __name__ == "__main__":
    main()

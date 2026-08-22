"""Standalone CLI to pull EOD prices from EODHD for all traded symbols + benchmark.

Usage (run with backend/ on PYTHONPATH, or from repo root):
    PYTHONPATH=backend python scripts/ingest_eodhd_eod.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.session import get_session
from app.services import market_data_service


def main() -> None:
    session = get_session()
    pairs = market_data_service.get_portfolio_symbols(session)
    print(f"Refreshing EOD prices for: {pairs}")
    rows = market_data_service.refresh_eod_prices(session, pairs)
    print(f"Ingested {rows} rows")


if __name__ == "__main__":
    main()

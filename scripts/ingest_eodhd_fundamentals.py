"""Standalone CLI to pull fundamentals from EODHD for all traded symbols.

Usage (run with backend/ on PYTHONPATH, or from repo root):
    PYTHONPATH=backend python scripts/ingest_eodhd_fundamentals.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.session import get_session
from app.services import market_data_service


def main() -> None:
    session = get_session()
    pairs = market_data_service.get_portfolio_symbols(session)
    print(f"Refreshing fundamentals for: {pairs}")
    rows = market_data_service.refresh_fundamentals(session, pairs)
    print(f"Ingested {rows} rows")


if __name__ == "__main__":
    main()

"""Standalone CLI to pull fundamentals from EODHD for all traded symbols.

Usage (from the repo root, with backend/.venv active):
    python scripts/ingest_eodhd_fundamentals.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.session import get_session  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.services import market_data_service  # noqa: E402

log = get_logger(__name__)


def main() -> None:
    session = get_session()
    pairs = market_data_service.get_portfolio_symbols(session)
    if not pairs:
        log.warning("No symbols to refresh - record some trades first")
        return
    log.info("Refreshing fundamentals for: %s", ", ".join(f"{s}.{e}" for s, e in pairs))
    rows = market_data_service.refresh_fundamentals(session, pairs)
    log.info("Ingested %d record(s)", rows)


if __name__ == "__main__":
    setup_logging(log_file="ingest.log")
    main()

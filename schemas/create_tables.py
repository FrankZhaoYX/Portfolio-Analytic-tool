"""Idempotently create every table in table_definitions.TABLES on the DB Service.

Usage:
    python schemas/create_tables.py
"""
import sys
from pathlib import Path

# Share the backend's settings and logging rather than re-deriving them, so this
# script honours DB_SERVICE_HOST / LOG_LEVEL from .env like the API does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import dbservice_client as dbs  # noqa: E402

from app.config import settings  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from table_definitions import TABLES  # noqa: E402

log = get_logger(__name__)


def main() -> None:
    log.info("Connecting to DB Service at %s", settings.db_service_host)
    session = dbs.Session(endpoint=settings.db_service_host)
    existing = set(session.list_tables())
    log.info("Existing tables: %s", sorted(existing) or "none")

    created = 0
    for name, definition in TABLES.items():
        if name in existing:
            log.info("skip   %s (already exists)", name)
            continue
        log.info("create %s ...", name)
        session.create_table(**definition)
        log.info("done   %s", name)
        created += 1

    log.info("Created %d new table(s). Final set: %s", created, sorted(session.list_tables()))


if __name__ == "__main__":
    setup_logging(log_file="schema.log")
    main()

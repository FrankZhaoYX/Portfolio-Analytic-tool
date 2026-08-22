import threading
import time
from functools import lru_cache

import dbservice_client as dbs

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

# The DB Service (0.1.0-beta.1) has been observed to corrupt on-disk partition
# directories when two ingest jobs (e.g. a trade insert and a bulk EOD-price
# import) run concurrently. Serialize all ingest calls through this lock.
INGEST_LOCK = threading.Lock()

# How often to log that a job is still running, so a stalled ingest announces
# itself instead of looking identical to a slow one.
_PROGRESS_EVERY_SECONDS = 15.0

_STALL_HINT = (
    "If ingests stall indefinitely, the DB Service has likely lost its internal "
    "message bus after a container restart (Docker restart / host sleep). Health "
    "checks and list_tables keep working in that state, which makes it look fine. "
    "Recovery is a full reset: cd db-service && docker compose down && rm -rf data "
    "&& bash init-db.sh && docker compose up -d, then rerun schemas/create_tables.py."
)


@lru_cache
def get_session() -> dbs.Session:
    log.info("Opening DB Service session at %s", settings.db_service_host)
    return dbs.Session(endpoint=settings.db_service_host)


def wait_for_import(
    session: dbs.Session, job_result: dict, timeout: float = 600.0, interval: float = 1.0
) -> dict:
    """Poll an import job returned by import_files/import_data until it finishes.

    If job_result has no 'name' (job id), the ingest was synchronous - return it as-is.
    """
    job_id = job_result.get("name") if isinstance(job_result, dict) else None
    if not job_id:
        log.debug("Ingest completed synchronously (no job id returned)")
        return job_result

    log.info("Ingest job %s submitted, waiting (timeout %.0fs)", job_id, timeout)
    started = time.monotonic()
    deadline = started + timeout
    next_progress = started + _PROGRESS_EVERY_SECONDS
    last_status = None

    while time.monotonic() < deadline:
        status_doc = session.get_import(job_id=job_id)
        status = status_doc.get("status")
        elapsed = time.monotonic() - started

        if status == "completed":
            log.info("Ingest job %s completed in %.1fs", job_id, elapsed)
            return status_doc

        if status == "errored":
            log.error(
                "Ingest job %s errored after %.1fs: %s",
                job_id,
                elapsed,
                status_doc.get("error") or status_doc,
            )
            raise RuntimeError(f"Import job {job_id} failed: {status_doc}")

        if status != last_status:
            log.debug("Ingest job %s status: %s (%.1fs)", job_id, status, elapsed)
            last_status = status

        now = time.monotonic()
        if now >= next_progress:
            # Escalate to WARNING: past ~15s a small ingest is not merely slow.
            log.warning(
                "Ingest job %s still '%s' after %.0fs (timeout %.0fs)",
                job_id,
                status,
                elapsed,
                timeout,
            )
            next_progress = now + _PROGRESS_EVERY_SECONDS

        time.sleep(interval)

    log.error("Ingest job %s timed out after %.0fs. %s", job_id, timeout, _STALL_HINT)
    raise TimeoutError(f"Import job {job_id} did not complete within {timeout}s. {_STALL_HINT}")

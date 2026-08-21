import threading
import time
from functools import lru_cache

import dbservice_client as dbs

from app.config import settings

# The DB Service (0.1.0-beta.1) has been observed to corrupt on-disk partition
# directories when two ingest jobs (e.g. a trade insert and a bulk EOD-price
# import) run concurrently. Serialize all ingest calls through this lock.
INGEST_LOCK = threading.Lock()


@lru_cache
def get_session() -> dbs.Session:
    return dbs.Session(endpoint=settings.db_service_host)


def wait_for_import(session: dbs.Session, job_result: dict, timeout: float = 600.0, interval: float = 1.0) -> dict:
    """Poll an import job returned by import_files/import_data until it finishes.

    If job_result has no 'name' (job id), the ingest was synchronous - return it as-is.
    """
    job_id = job_result.get("name") if isinstance(job_result, dict) else None
    if not job_id:
        return job_result

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = session.get_import(job_id=job_id)
        if status.get("status") == "completed":
            return status
        if status.get("status") == "errored":
            raise RuntimeError(f"Import job {job_id} failed: {status}")
        time.sleep(interval)

    raise TimeoutError(f"Import job {job_id} did not complete within {timeout}s")

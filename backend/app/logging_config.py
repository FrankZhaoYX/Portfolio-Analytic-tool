"""Central logging setup for the backend, CLI scripts, and schema tools.

Call `setup_logging()` once at process start (FastAPI does it in main.py,
scripts do it in their `__main__` block), then use `get_logger(__name__)`
in every module.

Two sinks:
  - stderr, for whatever terminal is running the process
  - a rotating file under `logs/`, so a hang or crash can be diagnosed
    after the fact rather than only while you happen to be watching

Every record carries a request id when one is in scope (see
`request_id_var`), so all the work done for a single HTTP request can be
followed across modules by grepping one id.
"""
import logging
import logging.handlers
import sys
from contextvars import ContextVar
from pathlib import Path

from app.config import settings

# Set per-request by the logging middleware in main.py. Anything logged while
# handling that request inherits the id, including from deep inside services.
# "-" is the default for work outside a request (startup, CLI scripts).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


class _RequestIdFilter(logging.Filter):
    """Injects the current request id so LOG_FORMAT can always reference it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(log_file: str = "backend.log") -> None:
    """Configure root logging. Idempotent - safe to call more than once."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    request_id_filter = _RequestIdFilter()

    root = logging.getLogger()
    root.setLevel(level)
    # Drop anything pre-existing (e.g. a basicConfig from an imported library)
    # so we don't double-emit every line.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(request_id_filter)
    root.addHandler(console)

    log_dir = Path(settings.log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_id_filter)
        root.addHandler(file_handler)
    except OSError as exc:  # read-only fs, permissions, etc - console still works
        root.warning("File logging disabled (%s): %s", log_dir, exc)

    # uvicorn installs its own handlers and disables propagation; re-point its
    # loggers at ours so access/error lines share one format and one file.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = list(root.handlers)
        uvicorn_logger.propagate = False

    # These are chatty at DEBUG and drown out our own lines.
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("matplotlib").setLevel(logging.INFO)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def redact(secret: str, keep: int = 4) -> str:
    """Render a secret safe to log: 'abcd...' with the tail withheld."""
    if not secret:
        return "<unset>"
    return f"{secret[:keep]}...<redacted>"

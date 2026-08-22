import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.logging_config import get_logger, redact, request_id_var, setup_logging
from app.routers import allocation, market_data, performance, positions, risk, trades

setup_logging()
log = get_logger(__name__)

app = FastAPI(title="Portfolio Analytic Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Tag each request with a short id, then log its outcome and duration.

    The id also goes back on the response as X-Request-ID, so a failure seen
    in the UI can be traced to the exact lines in logs/backend.log.
    """
    request_id = uuid.uuid4().hex[:8]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        log.info("--> %s %s", request.method, request.url.path)
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info(
            "<-- %s %s %s (%.0f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        # exception() captures the traceback; without this the only record of a
        # 500 was uvicorn's stderr dump, which is lost once the terminal scrolls.
        log.exception(
            "!!! %s %s raised after %.0f ms", request.method, request.url.path, elapsed_ms
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    finally:
        request_id_var.reset(token)


@app.on_event("startup")
def log_startup_config() -> None:
    log.info("Portfolio Analytic Tool backend starting")
    log.info("  DB Service      : %s", settings.db_service_host)
    log.info("  Imports dir     : %s", settings.db_service_imports_dir)
    log.info("  Benchmark       : %s", settings.benchmark_symbol)
    log.info("  Risk-free rate  : %s", settings.risk_free_rate)
    log.info("  EODHD API key   : %s", redact(settings.eodhd_api_key))
    log.info("  Log level / dir : %s / %s", settings.log_level, settings.log_dir)


app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(positions.router)
app.include_router(performance.router)
app.include_router(risk.router)
app.include_router(allocation.router)


@app.get("/health")
def health():
    return {"status": "ok"}

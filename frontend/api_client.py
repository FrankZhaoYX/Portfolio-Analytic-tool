import os

import pandas as pd
import requests
import streamlit as st

BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")

READ_TIMEOUT = 60
# Writes wait on a DB Service ingest. Those are slow on partitioned tables (a
# year of EOD history takes minutes), so this has to exceed the backend's own
# ingest timeout or the UI gives up on work that is still progressing fine.
WRITE_TIMEOUT = 660


def _describe(exc: requests.RequestException) -> str:
    """Error text for the user, including the backend request id when present.

    The id is the link between what the UI showed and the matching lines in
    logs/backend.log.
    """
    response = getattr(exc, "response", None)
    request_id = response.headers.get("X-Request-ID") if response is not None else None
    if isinstance(exc, requests.Timeout):
        detail = "timed out - the backend may be blocked on a stalled DB Service ingest"
    elif isinstance(exc, requests.ConnectionError):
        detail = f"could not reach the backend at {BASE_URL} - is uvicorn running?"
    else:
        detail = str(exc)
    return f"{detail} (request id: {request_id})" if request_id else detail


def _get(path: str, params: dict | None = None) -> dict | list:
    try:
        resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=READ_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Request to {path} failed: {_describe(exc)}")
        return {}


def _post(path: str, json: dict | None = None, files=None) -> dict:
    try:
        resp = requests.post(
            f"{BASE_URL}{path}", json=json, files=files, timeout=WRITE_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Request to {path} failed: {_describe(exc)}")
        return {}


def post_trade(trade: dict) -> dict:
    return _post("/api/trades", json=trade)


def upload_trades_csv(file) -> dict:
    return _post("/api/trades/upload", files={"file": (file.name, file.getvalue(), "text/csv")})


def get_trades(limit: int = 200) -> pd.DataFrame:
    data = _get("/api/trades", params={"limit": limit})
    return pd.DataFrame(data)


def refresh_market_data(scope: str = "all") -> dict:
    return _post("/api/market-data/refresh", json={"scope": scope})


def get_positions() -> pd.DataFrame:
    data = _get("/api/positions")
    return pd.DataFrame(data)


def get_pnl_history(from_date=None) -> pd.DataFrame:
    params = {"from_date": from_date.isoformat()} if from_date else None
    data = _get("/api/positions/pnl-history", params=params)
    return pd.DataFrame(data)


def get_performance(from_date=None, to_date=None) -> dict:
    params = {}
    if from_date:
        params["from_date"] = from_date.isoformat()
    if to_date:
        params["to_date"] = to_date.isoformat()
    return _get("/api/performance", params=params)


def get_risk_summary() -> dict:
    return _get("/api/risk/summary")


def get_correlation() -> dict:
    return _get("/api/risk/correlation")


def get_allocation(dimension: str = "assettype") -> dict:
    return _get("/api/allocation", params={"dimension": dimension})

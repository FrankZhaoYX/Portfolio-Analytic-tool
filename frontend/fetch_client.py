"""API client for the on-demand history endpoints.

Separate from api_client.py only so this feature could be added without editing
that file; fold these two functions into it when convenient.
"""
import os

import pandas as pd
import requests
import streamlit as st

BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")

# A fetch blocks until the DB Service ingest finishes. That is roughly a second
# per partition-day, so a multi-year pull genuinely takes minutes - this has to
# outlast the backend's own 600s ingest timeout or the UI abandons work that is
# still progressing.
FETCH_TIMEOUT = 900
READ_TIMEOUT = 60


def _describe(exc: requests.RequestException) -> str:
    response = getattr(exc, "response", None)
    request_id = response.headers.get("X-Request-ID") if response is not None else None
    if isinstance(exc, requests.Timeout):
        detail = (
            "timed out waiting for the ingest. It may still be running - check "
            "coverage in a minute before retrying, so you don't ingest twice"
        )
    elif isinstance(exc, requests.ConnectionError):
        detail = f"could not reach the backend at {BASE_URL} - is uvicorn running?"
    else:
        detail = str(exc)
        if response is not None:
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
    return f"{detail} (request id: {request_id})" if request_id else detail


def get_coverage() -> pd.DataFrame:
    """What's already stored, per symbol."""
    try:
        resp = requests.get(f"{BASE_URL}/api/market-data/coverage", timeout=READ_TIMEOUT)
        resp.raise_for_status()
        return pd.DataFrame(resp.json())
    except requests.RequestException as exc:
        st.error(f"Could not load coverage: {_describe(exc)}")
        return pd.DataFrame()


def list_symbols() -> list[str]:
    """Symbols that have stored price history."""
    try:
        resp = requests.get(f"{BASE_URL}/api/market-data/symbols", timeout=READ_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Could not load symbols: {_describe(exc)}")
        return []


def symbol_history(symbol: str, from_date=None, to_date=None) -> dict | None:
    """Price series and stats for one symbol."""
    params = {"symbol": symbol}
    if from_date:
        params["from_date"] = from_date.isoformat()
    if to_date:
        params["to_date"] = to_date.isoformat()
    try:
        resp = requests.get(
            f"{BASE_URL}/api/market-data/history", params=params, timeout=READ_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Could not load history for {symbol}: {_describe(exc)}")
        return None


def fetch_history(
    symbols: list[str],
    from_date=None,
    to_date=None,
    incremental: bool = False,
    dry_run: bool = False,
) -> dict | None:
    """Fetch and ingest EOD history. Returns None if the request failed."""
    body = {"symbols": symbols, "incremental": incremental, "dry_run": dry_run}
    if from_date:
        body["from_date"] = from_date.isoformat()
    if to_date:
        body["to_date"] = to_date.isoformat()
    try:
        resp = requests.post(
            f"{BASE_URL}/api/market-data/fetch",
            json=body,
            timeout=READ_TIMEOUT if dry_run else FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Fetch failed: {_describe(exc)}")
        return None

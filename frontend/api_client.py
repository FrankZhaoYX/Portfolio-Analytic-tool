import os

import pandas as pd
import requests
import streamlit as st

BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")


def _get(path: str, params: dict | None = None) -> dict | list:
    try:
        resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Request to {path} failed: {exc}")
        return {}


def _post(path: str, json: dict | None = None, files=None) -> dict:
    try:
        resp = requests.post(f"{BASE_URL}{path}", json=json, files=files, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Request to {path} failed: {exc}")
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

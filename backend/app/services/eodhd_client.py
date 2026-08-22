"""Thin wrapper around the EODHD REST API (https://eodhd.com/financial-apis).

All endpoints take a "TICKER.EXCHANGE" symbol, e.g. "AAPL.US".
"""
from datetime import date

import httpx

from app.config import settings

BASE_URL = "https://eodhd.com/api"


def _api_token() -> str:
    if not settings.eodhd_api_key:
        raise RuntimeError("EODHD_API_KEY is not set - add it to .env")
    return settings.eodhd_api_key


def get_eod_history(symbol: str, exchange: str, from_date: date, to_date: date) -> list[dict]:
    """Daily OHLCV history for one symbol, from_date/to_date inclusive."""
    resp = httpx.get(
        f"{BASE_URL}/eod/{symbol}.{exchange}",
        params={
            "api_token": _api_token(),
            "fmt": "json",
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def get_real_time_quotes(symbols: list[str]) -> list[dict]:
    """Real-time/delayed quotes for a batch of "TICKER.EXCHANGE" symbols.

    EODHD's real-time endpoint takes the first symbol in the path and the rest via `s=`.
    Returns a single dict for one symbol, or a list for multiple.
    """
    if not symbols:
        return []
    primary, *rest = symbols
    resp = httpx.get(
        f"{BASE_URL}/real-time/{primary}",
        params={"api_token": _api_token(), "fmt": "json", "s": ",".join(rest)} if rest else {
            "api_token": _api_token(),
            "fmt": "json",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else [data]


def get_fundamentals(symbol: str, exchange: str) -> dict:
    resp = httpx.get(
        f"{BASE_URL}/fundamentals/{symbol}.{exchange}",
        params={"api_token": _api_token(), "fmt": "json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()

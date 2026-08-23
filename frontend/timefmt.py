"""Display-side timezone conversion.

The backend stores and returns UTC (see backend/app/timeutil.py). Everything the
user reads is Eastern, converted here at the last possible moment.

America/New_York rather than a fixed -05:00, so EST/EDT switches automatically -
a hardcoded offset would silently shift every timestamp by an hour for most of
the year.
"""
from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")

# Timestamp columns that arrive from the API as UTC and should be shown as ET.
# Pure calendar dates (pxdate, asofdate, tradedate) are deliberately absent:
# a trade date is a calendar fact, not an instant, and shifting it by timezone
# would move trades across day boundaries.
UTC_COLUMNS = ("createdat", "ts")


def to_eastern(values) -> pd.Series:
    """Convert naive-UTC (or aware) timestamps to Eastern.

    Accepts a Series, list, or scalar; always returns a tz-aware Series in ET.
    Unparseable values become NaT rather than raising.
    """
    series = pd.to_datetime(pd.Series(values), errors="coerce", utc=False)
    if series.dt.tz is None:
        series = series.dt.tz_localize("UTC")
    else:
        series = series.dt.tz_convert("UTC")
    return series.dt.tz_convert(EASTERN)


def format_eastern(values, fmt: str = "%Y-%m-%d %H:%M:%S %Z") -> pd.Series:
    """Eastern timestamps rendered for display, with the zone label (EST/EDT)."""
    return to_eastern(values).dt.strftime(fmt)


def localize_frame(df: pd.DataFrame, columns=UTC_COLUMNS) -> pd.DataFrame:
    """Return a copy with the given UTC columns rendered as Eastern strings.

    Columns not present are skipped, so this is safe to call on any response.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = format_eastern(out[col])
    return out

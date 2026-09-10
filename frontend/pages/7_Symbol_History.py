from datetime import date, timedelta

import pandas as pd
import streamlit as st

import fetch_client

st.set_page_config(page_title="Symbol history", layout="wide")

# --- control bar: pick what to review --------------------------------------
# These controls drive this page and nothing else, so they belong at the top
# of the main area rather than the sidebar, which stays reserved for
# app-level navigation. Title and controls render before the fetch below so
# the page paints immediately instead of after the round trip.

st.title("Symbol history")

universe = fetch_client.list_universe()

if not universe:
    st.info(
        "No price history stored yet. Use **Add stock data** to pull some, "
        "then come back here."
    )
    st.stop()

# Group once, so each asset class keeps its own picker list and can show its
# own count. The class comes from data/universe/*.csv, not from eod_prices,
# which stores no asset-class column.
_LABELS = {"stock": "Stocks", "etf": "ETFs", "etp": "ETPs", "other": "Other"}
_ORDER = ["stock", "etf", "etp", "other"]

by_kind: dict[str, list[str]] = {}
for row in universe:
    by_kind.setdefault(row["kind"], []).append(row["symbol"])
for group in by_kind.values():
    group.sort()

all_symbols = sorted(row["symbol"] for row in universe)
# Only offer classes that actually have stored history, so the bar does not
# advertise an empty filter.
present = [k for k in _ORDER if by_kind.get(k)]

today = date.today()
_offsets = {
    "1 month": timedelta(days=31),
    "3 months": timedelta(days=92),
    "6 months": timedelta(days=183),
    "1 year": timedelta(days=365),
}

with st.container(horizontal=True, vertical_alignment="bottom", border=True):
    kind = st.segmented_control(
        "Asset class",
        ["all", *present],
        default="all",
        required=True,
        format_func=lambda k: (
            f"All ({len(all_symbols)})" if k == "all"
            else f"{_LABELS[k]} ({len(by_kind[k])})"
        ),
        help=(
            "ETPs are commodity trusts and leveraged/inverse products, which "
            "are not conventional ETFs. A ticker in both lists is filed under "
            "the narrower class, so GLD counts as an ETP."
        ),
    )
    # Switching class narrows the list; if the current pick is not in the new
    # one, Streamlit falls back to its first entry.
    choices = all_symbols if kind == "all" else by_kind[kind]
    symbol = st.selectbox(
        "Symbol",
        choices,
        help="Every symbol with stored price history.",
        width=240,
    )
    period = st.selectbox(
        "Period",
        ["1 month", "3 months", "6 months", "1 year", "Year to date", "All stored", "Custom"],
        index=3,
        width=200,
    )
    # The custom range inputs sit in the same bar and only exist when chosen;
    # the block runs top to bottom, so they appear beside Period, not below.
    if period == "Custom":
        from_date = st.date_input("From", value=today - timedelta(days=365), width=170)
        to_date = st.date_input("To", value=today, width=170)
    elif period == "Year to date":
        from_date, to_date = date(today.year, 1, 1), today
    elif period == "All stored":
        from_date, to_date = None, None
    else:
        from_date, to_date = today - _offsets[period], today

# --- load ------------------------------------------------------------------

data = fetch_client.symbol_history(symbol, from_date, to_date)

if not data or not data.get("series"):
    st.warning(
        f"No stored bars for **{symbol}** in this period. Try a wider period, "
        "or pull more history from **Add stock data**."
    )
    st.stop()

stats = data["stats"]
df = pd.DataFrame(data["series"])
df["pxdate"] = pd.to_datetime(df["pxdate"])
df = df.set_index("pxdate")

exchange = data.get("exchange")
st.caption(
    f"**{symbol}**{f' · {exchange}' if exchange else ''} — "
    f"{stats['bars']} trading days, {stats['first_date']} to {stats['last_date']}. "
    "This is the instrument's own performance; it takes no account of when you held it."
)

# --- headline numbers ------------------------------------------------------

sparkline = df["close"].tolist()

with st.container(horizontal=True):
    st.metric(
        "Total return",
        f"{stats['total_return']:.2%}",
        f"{stats['annualized_return']:.2%} annualized",
        border=True,
        chart_data=sparkline,
        chart_type="line",
    )
    st.metric("Last close", f"{stats['last_close']:,.2f}", border=True)
    st.metric("Volatility", f"{stats['annualized_volatility']:.2%}", border=True)
    st.metric("Sharpe", f"{stats['sharpe_ratio']:.2f}", border=True)
    st.metric("Max drawdown", f"{stats['max_drawdown']:.2%}", border=True)

# --- charts ----------------------------------------------------------------

left, right = st.columns(2)

with left:
    with st.container(border=True):
        st.subheader("Close price")
        st.line_chart(df["close"], height=280)

with right:
    with st.container(border=True):
        st.subheader("Cumulative return")
        st.area_chart(df["cum_return"] * 100, height=280, y_label="%")

with st.container(border=True):
    st.subheader("Drawdown")
    st.caption("Decline from the running peak — how far underwater the symbol was.")
    st.area_chart(df["drawdown"] * 100, height=220, y_label="%")

# --- detail ----------------------------------------------------------------

detail, table = st.columns([1, 2])

with detail:
    with st.container(border=True):
        st.subheader("Range")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Measure": "Period high", "Value": f"{stats['high']:,.2f}"},
                    {"Measure": "Period low", "Value": f"{stats['low']:,.2f}"},
                    {"Measure": "First close", "Value": f"{stats['first_close']:,.2f}"},
                    {"Measure": "Best day", "Value": f"{stats['best_day']:.2%}"},
                    {"Measure": "Worst day", "Value": f"{stats['worst_day']:.2%}"},
                    {"Measure": "Avg volume", "Value": f"{stats['avg_volume']:,.0f}"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )

with table:
    with st.container(border=True):
        st.subheader("Daily bars")
        recent = df.sort_index(ascending=False).reset_index()
        recent["pxdate"] = recent["pxdate"].dt.date
        st.dataframe(
            recent.rename(
                columns={
                    "pxdate": "Date", "close": "Close",
                    "cum_return": "Cumulative return", "drawdown": "Drawdown",
                    "volume": "Volume",
                }
            ),
            width="stretch",
            hide_index=True,
            height=280,
            column_config={
                "Close": st.column_config.NumberColumn(format="%.2f"),
                "Cumulative return": st.column_config.NumberColumn(format="percent"),
                "Drawdown": st.column_config.NumberColumn(format="percent"),
                "Volume": st.column_config.NumberColumn(format="localized"),
            },
        )

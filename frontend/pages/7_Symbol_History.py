from datetime import date, timedelta

import pandas as pd
import streamlit as st

import fetch_client

st.set_page_config(page_title="Symbol history", layout="wide")

# --- sidebar: pick what to review -----------------------------------------

symbols = fetch_client.list_symbols()

st.sidebar.header("Review a symbol", divider="gray")

if not symbols:
    st.sidebar.info("No price history stored yet.")
    st.title("Symbol history")
    st.info(
        "No price history stored yet. Use **Add stock data** to pull some, "
        "then come back here."
    )
    st.stop()

symbol = st.sidebar.selectbox(
    "Symbol",
    symbols,
    help="Every symbol with stored price history.",
)

today = date.today()
period = st.sidebar.selectbox(
    "Period",
    ["1 month", "3 months", "6 months", "1 year", "Year to date", "All stored", "Custom"],
    index=3,
)

_offsets = {
    "1 month": timedelta(days=31),
    "3 months": timedelta(days=92),
    "6 months": timedelta(days=183),
    "1 year": timedelta(days=365),
}
if period == "Custom":
    from_date = st.sidebar.date_input("From", value=today - timedelta(days=365))
    to_date = st.sidebar.date_input("To", value=today)
elif period == "Year to date":
    from_date, to_date = date(today.year, 1, 1), today
elif period == "All stored":
    from_date, to_date = None, None
else:
    from_date, to_date = today - _offsets[period], today

# --- load ------------------------------------------------------------------

data = fetch_client.symbol_history(symbol, from_date, to_date)

st.title("Symbol history")

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

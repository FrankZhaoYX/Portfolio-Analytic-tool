import streamlit as st

from components.sidebar import render_refresh_button

st.set_page_config(page_title="Portfolio Analytic Tool", layout="wide")

render_refresh_button()

st.title("Portfolio Analytic Tool")
st.markdown(
    """
    Use the pages in the sidebar to:
    - **Trade Entry** — record buys/sells manually or via CSV upload
    - **Positions & P&L** — current holdings and profit/loss
    - **Performance** — returns vs benchmark
    - **Risk** — volatility, Sharpe, drawdown, VaR, correlation
    - **Allocation** — exposure by asset class, sector, geography

    Click **Refresh Market Data** in the sidebar after entering trades to pull
    the latest prices and fundamentals from EODHD.
    """
)

import pandas as pd
import streamlit as st

import api_client
from components.sidebar import render_date_range, render_refresh_button

st.set_page_config(page_title="Performance", layout="wide")
render_refresh_button()
st.title("Performance")

from_date, to_date = render_date_range()

summary = api_client.get_performance(from_date=from_date, to_date=to_date)
if not summary or not summary.get("points"):
    st.info("No performance data yet. Enter trades and refresh market data first.")
else:
    col1, col2 = st.columns(2)
    col1.metric("Time-Weighted Return", f"{summary['twr'] * 100:.2f}%")
    col2.metric("Money-Weighted Return (XIRR)", f"{summary['mwr'] * 100:.2f}%" if summary.get("mwr") is not None else "N/A")

    points_df = pd.DataFrame(summary["points"])
    points_df["as_of"] = pd.to_datetime(points_df["as_of"])
    points_df = points_df.set_index("as_of")
    st.line_chart(points_df[["portfolio_cum_return", "benchmark_cum_return"]] * 100)

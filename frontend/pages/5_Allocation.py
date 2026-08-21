import pandas as pd
import streamlit as st

import api_client
from components.sidebar import render_refresh_button

st.set_page_config(page_title="Allocation", layout="wide")
render_refresh_button()
st.title("Allocation & Exposure")

dimension = st.selectbox("Breakdown by", ["assettype", "sector", "country", "symbol"])

breakdown = api_client.get_allocation(dimension=dimension)
if breakdown and breakdown.get("slices"):
    slices_df = pd.DataFrame(breakdown["slices"])
    col1, col2 = st.columns([1, 1])
    with col1:
        st.bar_chart(slices_df.set_index("label")["weight_pct"])
    with col2:
        st.dataframe(
            slices_df.style.format({"market_value": "${:,.2f}", "weight_pct": "{:.1f}%"}),
            use_container_width=True,
        )
else:
    st.info("No allocation data yet. Enter trades and refresh market data first.")

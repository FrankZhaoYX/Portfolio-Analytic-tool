import pandas as pd
import streamlit as st

import api_client
from components.sidebar import render_refresh_button

st.set_page_config(page_title="Risk", layout="wide")
render_refresh_button()
st.title("Risk")

summary = api_client.get_risk_summary()
if summary:
    col1, col2, col3 = st.columns(3)
    col1.metric("Annualized Volatility", f"{summary.get('annualized_volatility', 0) * 100:.2f}%")
    col2.metric("Sharpe Ratio", f"{summary.get('sharpe_ratio', 0):.2f}")
    col3.metric("Max Drawdown", f"{summary.get('max_drawdown', 0) * 100:.2f}%")

    col4, col5 = st.columns(2)
    col4.metric("VaR (historical, 95%)", f"{summary.get('var_historical_95', 0) * 100:.2f}%")
    col5.metric("VaR (parametric, 95%)", f"{summary.get('var_parametric_95', 0) * 100:.2f}%")

st.subheader("Correlation Matrix")
corr = api_client.get_correlation()
if corr and corr.get("symbols"):
    corr_df = pd.DataFrame(corr["matrix"], index=corr["symbols"], columns=corr["symbols"])
    st.dataframe(corr_df.style.format("{:.2f}").background_gradient(cmap="RdYlGn", vmin=-1, vmax=1))
else:
    st.info("Not enough data for a correlation matrix yet.")

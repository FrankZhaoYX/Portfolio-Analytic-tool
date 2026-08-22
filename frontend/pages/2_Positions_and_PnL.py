import streamlit as st

import api_client
from components.sidebar import render_refresh_button

st.set_page_config(page_title="Positions & P&L", layout="wide")
render_refresh_button()
st.title("Positions & P&L")

positions_df = api_client.get_positions()
if positions_df.empty:
    st.info("No open positions yet. Enter trades and refresh market data first.")
else:
    st.dataframe(
        positions_df.style.format(
            {
                "avg_cost": "{:.2f}",
                "current_price": "{:.2f}",
                "market_value": "{:.2f}",
                "unrealized_pnl": "{:.2f}",
                "weight_pct": "{:.1f}%",
            }
        ),
        use_container_width=True,
    )

    total_mv = positions_df["market_value"].sum()
    total_upnl = positions_df["unrealized_pnl"].sum()
    col1, col2 = st.columns(2)
    col1.metric("Total Market Value", f"${total_mv:,.2f}")
    col2.metric("Total Unrealized P&L", f"${total_upnl:,.2f}")

st.subheader("Cumulative P&L Over Time")
pnl_history_df = api_client.get_pnl_history()
if not pnl_history_df.empty:
    pnl_history_df["as_of"] = pnl_history_df["as_of"]
    pnl_history_df["total_pnl"] = pnl_history_df["unrealized_pnl"] + pnl_history_df["realized_pnl_cum"]
    st.line_chart(pnl_history_df.set_index("as_of")[["unrealized_pnl", "realized_pnl_cum", "total_pnl"]])
else:
    st.info("No P&L history available yet.")

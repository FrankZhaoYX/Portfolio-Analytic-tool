from datetime import date

import streamlit as st

import api_client
import timefmt
from components.sidebar import render_refresh_button

st.set_page_config(page_title="Trade Entry", layout="wide")
render_refresh_button()
st.title("Trade Entry")

manual_tab, csv_tab = st.tabs(["Manual Entry", "CSV Upload"])

with manual_tab:
    with st.form("trade_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        symbol = col1.text_input("Symbol", placeholder="AAPL")
        exchange = col2.text_input("Exchange", value="US")
        side = col3.selectbox("Side", ["BUY", "SELL"])

        col4, col5, col6 = st.columns(3)
        qty = col4.number_input("Quantity", min_value=0.0, step=1.0)
        price = col5.number_input("Price", min_value=0.0, step=0.01)
        trade_date = col6.date_input("Trade Date", value=date.today())

        col7, col8 = st.columns(2)
        fees = col7.number_input("Fees", min_value=0.0, step=0.01, value=0.0)
        currency = col8.text_input("Currency", value="USD")

        notes = st.text_input("Notes", value="")
        submitted = st.form_submit_button("Submit Trade")

        if submitted:
            if not symbol or qty <= 0 or price <= 0:
                st.error("Symbol, quantity, and price are required.")
            else:
                result = api_client.post_trade(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "tradedate": trade_date.isoformat(),
                        "fees": fees,
                        "currency": currency,
                        "notes": notes,
                    }
                )
                if result:
                    st.success(f"Trade recorded: {result}")

with csv_tab:
    st.write("CSV must include columns: symbol, exchange, side, qty, price, tradedate. Optional: fees, currency, notes.")
    uploaded = st.file_uploader("Upload trades CSV", type="csv")
    if uploaded is not None:
        import pandas as pd

        preview = pd.read_csv(uploaded)
        st.dataframe(preview)
        if st.button("Submit CSV"):
            uploaded.seek(0)
            result = api_client.upload_trades_csv(uploaded)
            if result:
                st.success(f"Inserted {result.get('inserted', 0)} trades")

st.subheader("Recent Trades")
trades_df = api_client.get_trades()
if not trades_df.empty:
    # createdat is stored UTC; show it in Eastern. tradedate is left alone -
    # it's a calendar date, and shifting it by timezone would move trades
    # across day boundaries.
    st.dataframe(timefmt.localize_frame(trades_df), width="stretch")
    st.caption("Times shown in Eastern; stored in UTC.")
else:
    st.info("No trades recorded yet.")

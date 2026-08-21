from datetime import date, timedelta

import streamlit as st

import api_client


def render_refresh_button():
    if st.sidebar.button("Refresh Market Data"):
        with st.spinner("Refreshing EOD prices, quotes, and fundamentals..."):
            result = api_client.refresh_market_data(scope="all")
        st.sidebar.success(f"Refreshed: {result}")


def render_date_range(default_days: int = 365) -> tuple[date, date]:
    today = date.today()
    start = st.sidebar.date_input("From", value=today - timedelta(days=default_days))
    end = st.sidebar.date_input("To", value=today)
    return start, end

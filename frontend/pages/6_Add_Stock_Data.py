from datetime import date, timedelta

import pandas as pd
import streamlit as st

import fetch_client
from components.sidebar import render_refresh_button

st.set_page_config(page_title="Add Stock Data", layout="wide")
render_refresh_button()

st.title("Add Stock Data")
st.caption(
    "Pull end-of-day price history for any symbol and store it. "
    "Use this for tickers you don't hold yet, or to extend history further back "
    "than the standard refresh window."
)

# --- what's already stored -------------------------------------------------

coverage = fetch_client.get_coverage()

with st.expander("What's already stored", expanded=not coverage.empty):
    if coverage.empty:
        st.info("No price history stored yet.")
    else:
        display = coverage.rename(
            columns={
                "symbol": "Symbol", "rows": "Rows", "days": "Trading days",
                "first": "From", "last": "To", "duplicates": "Duplicate rows",
            }
        )
        st.dataframe(display, width="stretch", hide_index=True)
        dupes = int(coverage["duplicates"].sum())
        if dupes:
            st.warning(
                f"{dupes:,} duplicate row(s) across {int((coverage['duplicates'] > 0).sum())} "
                "symbol(s). Re-ingesting a date range that's already stored appends rather "
                "than replaces. Tick **Skip dates already stored** below to avoid adding more."
            )

# --- the form --------------------------------------------------------------

st.subheader("Fetch history")

with st.form("fetch_form"):
    symbols_raw = st.text_input(
        "Symbols",
        placeholder="TQQQ.US, VDY.TO, SPY",
        help=(
            "Comma or space separated, as TICKER.EXCHANGE. A bare ticker assumes "
            "`.US`, so anything listed elsewhere needs its suffix — Toronto is "
            "`.TO`, London `.L`, XETRA `.DE`, Hong Kong `.HK`, ASX `.AU`, "
            "indices `.INDX`."
        ),
    )

    col1, col2 = st.columns(2)
    today = date.today()
    from_date = col1.date_input("From", value=today - timedelta(days=365))
    to_date = col2.date_input("To", value=today)

    incremental = st.checkbox(
        "Skip dates already stored",
        value=True,
        help=(
            "Resume each symbol the day after its newest stored bar. Prevents "
            "duplicate rows, and makes repeated top-ups cheap."
        ),
    )

    preview, submit = st.columns([1, 1])
    do_preview = preview.form_submit_button("Preview", width="stretch")
    do_fetch = submit.form_submit_button(
        "Fetch and save", type="primary", width="stretch"
    )

symbols = [s for s in symbols_raw.replace(",", " ").split() if s]


def render_plan(result: dict) -> None:
    plan = result.get("plan", [])
    skipped = result.get("skipped", [])
    if skipped:
        st.info(f"Already current, skipping: {', '.join(skipped)}")
    if not plan:
        st.success("Nothing to fetch — everything requested is already stored.")
        return
    st.write(f"**{len(plan)} symbol(s) to fetch:**")
    st.dataframe(
        pd.DataFrame(plan)[["label", "start", "end", "span_days"]].rename(
            columns={
                "label": "Symbol", "start": "From", "end": "To", "span_days": "Day span",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    total = sum(p["span_days"] for p in plan)
    if total > 2000:
        st.warning(
            f"Large pull (~{total:,} symbol-days). Ingest writes roughly one partition "
            "per calendar day, so expect several minutes."
        )


if do_preview or do_fetch:
    if not symbols:
        st.error("Enter at least one symbol.")
    elif from_date > to_date:
        st.error("The From date is after the To date.")
    else:
        if do_preview:
            result = fetch_client.fetch_history(
                symbols, from_date, to_date, incremental, dry_run=True
            )
            if result:
                render_plan(result)
                st.caption("Preview only — nothing was fetched or saved.")
        else:
            with st.spinner("Fetching from EODHD and ingesting… this can take a few minutes."):
                result = fetch_client.fetch_history(
                    symbols, from_date, to_date, incremental, dry_run=False
                )
            if result:
                render_plan(result)

                failed = result.get("failed") or {}
                no_data = result.get("no_data") or {}
                per_symbol = result.get("per_symbol") or {}
                ingested = result.get("ingested", 0)

                if ingested:
                    st.success(
                        f"Saved {ingested:,} row(s) across {len(per_symbol)} symbol(s), "
                        f"~{result.get('partition_days', 0):,} partition-day(s)."
                    )
                    st.dataframe(
                        pd.DataFrame(
                            [{"Symbol": k, "Bars fetched": v} for k, v in per_symbol.items()]
                        ),
                        width="stretch",
                        hide_index=True,
                    )
                elif not failed and not no_data:
                    st.info("Nothing new to save.")

                for label, message in no_data.items():
                    st.warning(f"**{label}** — {message}")

                for label, message in failed.items():
                    st.error(f"{label}: {message}")

                if ingested:
                    st.rerun()

"""Static vs dynamic hedge ratio between two ETFs, on stored history.

Methodology follows Alexzap, "Static ETF-ETF Hedge Ratios Are Dead: How PyDLM
Dynamically Hedges SPY-QQQ". The data is this project's own `eod_prices`
table, so nothing here calls a vendor API.
"""
import numpy as np
import pandas as pd
import streamlit as st

import fetch_client

st.set_page_config(page_title="Static analysis SPY QQQ", layout="wide")

st.title("Static analysis: SPY and QQQ")

universe = fetch_client.list_universe()
if not universe:
    st.info(
        "No price history stored yet. Use **Add stock data** to pull some, "
        "then come back here."
    )
    st.stop()

symbols = sorted(row["symbol"] for row in universe)


def _default(sym: str, fallback: int) -> int:
    return symbols.index(sym) if sym in symbols else fallback


with st.container(horizontal=True, vertical_alignment="bottom", border=True):
    y_symbol = st.selectbox(
        "Asset (hedged)", symbols, index=_default("QQQ", 0), width=170,
        help="The instrument whose price is being explained - the regressand.",
    )
    x_symbol = st.selectbox(
        "Hedge instrument", symbols, index=_default("SPY", 0), width=180,
        help="The instrument used to hedge it - the regressor.",
    )
    discount = st.slider(
        "DLM discount", 0.50, 1.00, 0.70, 0.05, width=210,
        help="The model's memory. Lower forgets faster, so beta tracks regime "
             "changes more sharply but reacts more to noise. 1.0 is no "
             "discounting, which collapses towards a static fit.",
    )
    rolling_window = st.slider(
        "Rolling window (days)", 20, 250, 60, 10, width=210,
        help="Lookback for the rolling-OLS comparison.",
    )
    test_pct = st.slider(
        "Out-of-sample %", 10, 50, 20, 5, width=180,
        help="Share of the most recent history held back for evaluation.",
    )

if y_symbol == x_symbol:
    st.warning("Pick two different symbols - regressing a series on itself is degenerate.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def _run(y, x, disc, win, frac):
    return fetch_client.hedge_analysis(
        y, x, discount=disc, rolling_window=win, test_fraction=frac
    )


with st.spinner(f"Fitting static, rolling and DLM hedge ratios for {y_symbol}~{x_symbol}…"):
    res = _run(y_symbol, x_symbol, discount, rolling_window, test_pct / 100.0)

if not res:
    st.stop()

st.caption(
    f"**{res['y_symbol']}** regressed on **{res['x_symbol']}** in log adjusted "
    f"close, {res['first_date']} to {res['last_date']} "
    f"({res['n_total']:,} common trading days). Fitted on the first "
    f"{res['n_train']:,} (through {res['train_end']}); the last "
    f"{res['n_test']:,} are held out and never seen during fitting."
)

metrics = pd.DataFrame(res["metrics"]).set_index("model")
best = metrics["rmse"].idxmin()
static_rmse = float(metrics.loc["Static", "rmse"])

# --- headline numbers ------------------------------------------------------

with st.container(horizontal=True):
    st.metric("Static hedge ratio", f"{res['beta_static']:.4f}", border=True)
    for model in ("Static", "Rolling", "PyDLM"):
        rmse = float(metrics.loc[model, "rmse"])
        delta = None if model == "Static" else f"{rmse / static_rmse - 1:.1%} vs static"
        st.metric(
            f"{model} RMSE", f"{rmse:.5f}", delta,
            delta_color="inverse", border=True,
        )

st.caption(
    f"Lowest out-of-sample RMSE: **{best}**. A hedge ratio of "
    f"{res['beta_static']:.2f} means a 1% move in {res['x_symbol']} historically "
    f"came with roughly a {res['beta_static']:.2f}% move in {res['y_symbol']}."
)

oos = pd.DataFrame(res["oos"])
oos["date"] = pd.to_datetime(oos["date"])
oos = oos.set_index("date")

ins = pd.DataFrame(res["in_sample"])
ins["date"] = pd.to_datetime(ins["date"])
ins = ins.set_index("date")

# --- hedge ratio through time ----------------------------------------------

left, right = st.columns(2)

with left:
    with st.container(border=True):
        st.subheader("In-sample hedge ratio")
        st.caption("DLM beta as it evolved over the training period, against the single static estimate.")
        st.line_chart(
            pd.DataFrame({
                "PyDLM β(t)": ins["beta_pydlm"],
                "Static β": res["beta_static"],
            }),
            height=280, y_label="Beta",
        )

with right:
    with st.container(border=True):
        st.subheader("Out-of-sample hedge ratio")
        st.caption("The same comparison on data none of the models were fitted on.")
        st.line_chart(
            pd.DataFrame({
                "PyDLM": oos["beta_pydlm"],
                "Rolling OLS": oos["beta_rolling"],
                "Static": res["beta_static"],
            }),
            height=280, y_label="Beta",
        )

# --- prediction and residuals ----------------------------------------------

with st.container(border=True):
    st.subheader(f"{res['y_symbol']} prediction, out of sample")
    st.caption(
        f"Each model's implied {res['y_symbol']} price given the "
        f"contemporaneous {res['x_symbol']} price, converted back from logs."
    )
    st.line_chart(
        pd.DataFrame({
            "Actual": oos["actual_price"],
            "Static": oos["static_price"],
            "Rolling": oos["rolling_price"],
            "PyDLM": oos["pydlm_price"],
        }),
        height=320, y_label="Price",
    )

with st.container(border=True):
    st.subheader("Hedge residuals")
    st.caption("Actual minus predicted, in log space. Flatter and tighter to zero is a better hedge.")
    st.line_chart(
        pd.DataFrame({
            "Static": oos["resid_static"],
            "Rolling": oos["resid_rolling"],
            "PyDLM": oos["resid_pydlm"],
        }),
        height=280, y_label="Residual",
    )

low, high = st.columns(2)

with low:
    with st.container(border=True):
        st.subheader("Rolling residual volatility")
        st.caption("20-day standard deviation of each model's residual.")
        st.line_chart(
            pd.DataFrame({
                "Static": oos["vol_static"],
                "Rolling": oos["vol_rolling"],
                "PyDLM": oos["vol_pydlm"],
            }).dropna(),
            height=260, y_label="20-day std",
        )

with high:
    with st.container(border=True):
        st.subheader("Residual distribution")
        st.caption("Where each model's errors land. A tighter, more centred spike is better.")
        cols = {"Static": "resid_static", "Rolling": "resid_rolling", "PyDLM": "resid_pydlm"}
        stacked = np.concatenate([oos[c].dropna().to_numpy() for c in cols.values()])
        edges = np.histogram_bin_edges(stacked, bins=30)
        mids = (edges[:-1] + edges[1:]) / 2
        hist = pd.DataFrame(
            {name: np.histogram(oos[c].dropna().to_numpy(), bins=edges)[0]
             for name, c in cols.items()},
            # Shared bins across models, so the three are directly comparable.
            index=np.round(mids, 4),
        )
        st.bar_chart(hist, height=260, stack=False, x_label="Residual", y_label="Days")

# --- metrics ---------------------------------------------------------------

with st.container(border=True):
    st.subheader("Out-of-sample performance")
    table = metrics.rename(columns={
        "rmse": "RMSE", "mae": "MAE", "std": "Std",
        "skew": "Skew", "kurtosis": "Kurtosis",
    }).reset_index().rename(columns={"model": "Model"})
    st.dataframe(
        table, width="stretch", hide_index=True,
        column_config={
            "RMSE": st.column_config.NumberColumn(format="%.5f"),
            "MAE": st.column_config.NumberColumn(format="%.5f"),
            "Std": st.column_config.NumberColumn(format="%.5f"),
            "Skew": st.column_config.NumberColumn(format="%.4f"),
            "Kurtosis": st.column_config.NumberColumn(format="%.4f"),
        },
    )
    st.caption(
        "RMSE and MAE measure typical error size, lower is better. Std is the "
        "spread of the residuals. Skew and Fisher kurtosis describe the shape "
        "of the error distribution rather than its size, so they say how the "
        "model fails, not how often."
    )

with st.expander("Method, and where it departs from the article"):
    st.markdown(
        f"""
The model treats the hedge ratio as something that moves:

    log {res['y_symbol']}(t) = α(t) + β(t)·log {res['x_symbol']}(t) + noise(t)

**Static OLS** fits one β on the training split and holds it fixed.
**Rolling OLS** refits on a trailing {res['rolling_window']}-day window, so β moves,
but every day inside the window counts equally and everything outside it counts
for nothing. **PyDLM** treats α and β as latent states updated by a Kalman
filter, so each new day shifts the estimate in proportion to how surprising it
was, with a discount factor of {res['discount']} controlling how fast old data
is forgotten.

**Two deliberate departures from the article:**

1. *Data source.* The article downloads from yfinance; this reads your stored
   `eod_prices`, using `adjclose` rather than `close`. Raw close double-counts
   splits and ignores dividends, which would drag the fitted β.

2. *Computation, not method.* The article refits the DLM from scratch at every
   out-of-sample step, which is O(n²) — about 55 seconds over ten years here.
   Forward filtering is causal, so the last state of a model fit on history
   up to *t* equals the state at *t* of one fit over the whole series. This
   fits once and slices, which was verified to agree to **0.0e+00** on both α
   and β against the article's loop on this exact data. Backward smoothing
   would look ahead and is deliberately not used.

**A caveat worth keeping.** The comparison is favourable to the DLM partly by
construction: predicting {res['y_symbol']}(t) uses the contemporaneous
{res['x_symbol']}(t). That is the right question for hedging — given today's
move in the hedge instrument, how much shows up in the asset — but it is not a
forecast, and these RMSEs should not be read as predictive accuracy.
        """
    )

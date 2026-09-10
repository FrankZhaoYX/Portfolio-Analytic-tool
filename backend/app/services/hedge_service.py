"""Dynamic hedge ratio between two symbols, via a Bayesian dynamic linear model.

Methodology follows Alexzap, "Static ETF-ETF Hedge Ratios Are Dead: How PyDLM
Dynamically Hedges SPY-QQQ" (Medium). The data is this project's own stored
history in `eod_prices`, not a vendor download.

The relationship modelled is

    log P_y(t) = alpha(t) + beta(t) * log P_x(t) + noise(t)

where beta is the hedge ratio. Three estimators are compared out of sample:

  * **static OLS** - one beta fitted on the training split and held fixed.
  * **rolling OLS** - beta refitted on a trailing fixed-length window, so it
    moves, but only as fast as the window lets it and with equal weight on
    every observation inside it.
  * **PyDLM** - alpha and beta are latent states updated by a Kalman filter
    with discount factors, so each observation shifts the estimate by an
    amount that depends on how surprising it was.

WHY ONE FIT INSTEAD OF THE ARTICLE'S REFIT LOOP
-----------------------------------------------
The article re-fits the DLM from scratch at every out-of-sample step, on a
history that grows by one observation each time. That is O(n^2) - about 55
seconds over ten years of daily data here, which is too slow to sit behind a
page load.

It is also unnecessary. Forward filtering is causal: the filtered state at
time t depends only on observations up to t, so the last state of a model fit
on history[:t] equals the state at t-1 of a single model fit over the whole
series. Verified on this data path - the two agree to 0.0e+00 on both alpha
and beta - so this fits once and slices, which is the same numbers ~36x
faster. Backward smoothing would peek ahead and is deliberately not used.

The out-of-sample predictions stay honest under this scheme: predicting y(t)
uses the state filtered through t-1 together with the *contemporaneous* x(t),
which is exactly the hedging question - given today's move in the hedge
instrument, how much of it should show up in the asset.
"""
import logging
from datetime import date

import dbservice_client as dbs
import numpy as np
import pandas as pd

from app.db.tables import EOD_PRICES
from app.logging_config import get_logger

# PyDLM narrates every filtering pass at INFO, which would swamp the app log.
logging.getLogger("pydlm").setLevel(logging.WARNING)

log = get_logger(__name__)

ROLLING_VOL_WINDOW = 20


def _load_pair(
    session: dbs.Session,
    y_symbol: str,
    x_symbol: str,
    from_date: date | None,
    to_date: date | None,
) -> pd.DataFrame:
    """Log adjusted-close series for both symbols, aligned on common dates.

    `adjclose` rather than `close`: raw close double-counts splits and ignores
    dividends, so a split shows up as a fake one-day crash and would drag the
    fitted hedge ratio with it.
    """
    clauses = [f"symbol IN ('{y_symbol.upper()}', '{x_symbol.upper()}')"]
    if from_date:
        clauses.append(f"pxdate >= '{from_date.isoformat()}'")
    if to_date:
        clauses.append(f"pxdate <= '{to_date.isoformat()}'")

    df = session.query_sql(
        query=f"SELECT pxdate, symbol, adjclose FROM {EOD_PRICES} "
              f"WHERE {' AND '.join(clauses)}",
        return_as="pandas",
    )
    if df.empty:
        return pd.DataFrame()

    df["pxdate"] = pd.to_datetime(df["pxdate"]).dt.normalize()
    df["symbol"] = df["symbol"].astype(str).str.upper()
    # Re-ingesting an overlapping range appends rather than replaces, so keep
    # one row per symbol-day before pivoting or the pivot silently averages.
    df = df.drop_duplicates(subset=["symbol", "pxdate"], keep="last")

    wide = df.pivot(index="pxdate", columns="symbol", values="adjclose")
    for sym in (y_symbol.upper(), x_symbol.upper()):
        if sym not in wide.columns:
            return pd.DataFrame()

    # Inner join on dates: a hedge ratio needs both legs on the same session,
    # and the two can differ (different exchange holidays, late listings).
    wide = wide[[y_symbol.upper(), x_symbol.upper()]].dropna()
    wide = wide[(wide > 0).all(axis=1)]
    return pd.DataFrame(
        {"y": np.log(wide[y_symbol.upper()]), "x": np.log(wide[x_symbol.upper()])},
        index=wide.index,
    )


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """Intercept and slope of y on x by least squares."""
    design = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(coef[0]), float(coef[1])


def _metrics(resid: np.ndarray) -> dict:
    """RMSE, MAE, dispersion and shape of a residual series.

    Skew and Fisher kurtosis are computed directly rather than pulling in
    SciPy for two formulas; these match `scipy.stats.skew/kurtosis` defaults
    (biased, population moments).
    """
    r = np.asarray(resid, dtype=float)
    n = len(r)
    centred = r - r.mean()
    sigma = float(np.sqrt((centred ** 2).mean())) if n else 0.0
    return {
        "rmse": float(np.sqrt((r ** 2).mean())) if n else 0.0,
        "mae": float(np.abs(r).mean()) if n else 0.0,
        "std": float(r.std(ddof=1)) if n > 1 else 0.0,
        "skew": float((centred ** 3).mean() / sigma ** 3) if sigma else 0.0,
        "kurtosis": float((centred ** 4).mean() / sigma ** 4 - 3.0) if sigma else 0.0,
    }


def _pydlm_states(y: np.ndarray, x: np.ndarray, discount: float) -> np.ndarray:
    """Forward-filtered [alpha(t), beta(t)] for the whole series.

    A degree-0 trend supplies the time-varying intercept and a single dynamic
    regressor on x supplies the time-varying slope. `discount` is the model's
    memory: lower forgets faster, so beta tracks regime changes more sharply
    at the cost of reacting to noise.
    """
    from pydlm import dlm, dynamic, trend

    model = (
        dlm(list(y))
        + trend(degree=0, discount=discount, name="intercept")
        + dynamic(features=[[v] for v in x], discount=discount, name="beta")
    )
    model.fitForwardFilter()
    states = np.asarray(
        model.getLatentState(filterType="forwardFilter", name="all"), dtype=float
    )
    return states.reshape(len(y), -1)


def hedge_analysis(
    session: dbs.Session,
    y_symbol: str = "QQQ",
    x_symbol: str = "SPY",
    from_date: date | None = None,
    to_date: date | None = None,
    test_fraction: float = 0.20,
    rolling_window: int = 60,
    discount: float = 0.70,
) -> dict:
    """Compare static, rolling and DLM hedge ratios out of sample."""
    data = _load_pair(session, y_symbol, x_symbol, from_date, to_date)
    if data.empty:
        return {"error": "no_overlapping_history", "y_symbol": y_symbol.upper(),
                "x_symbol": x_symbol.upper()}

    n_total = len(data)
    n_test = int(n_total * test_fraction)
    n_train = n_total - n_test
    # Rolling OLS needs a full window inside the training split before the
    # out-of-sample walk starts, or its first estimates are fitted on nothing.
    if n_test < 2 or n_train <= rolling_window:
        return {
            "error": "insufficient_history",
            "detail": f"{n_total} overlapping days give {n_train} training and "
                      f"{n_test} test rows; need more than {rolling_window} "
                      "training rows and at least 2 test rows.",
            "y_symbol": y_symbol.upper(), "x_symbol": x_symbol.upper(),
        }

    y = data["y"].to_numpy()
    x = data["x"].to_numpy()
    dates = data.index

    alpha_static, beta_static = _ols(y[:n_train], x[:n_train])

    # PyDLM once over the whole series; see the module docstring for why this
    # is equivalent to the article's per-step refit.
    states = _pydlm_states(y, x, discount)
    alpha_dlm, beta_dlm = states[:, 0], states[:, 1]

    static_pred, rolling_pred, dlm_pred = [], [], []
    rolling_beta_oos = []
    for i in range(n_test):
        t = n_train + i
        static_pred.append(alpha_static + beta_static * x[t])

        # Trailing window over everything revealed so far - training data plus
        # the test days already stepped through.
        lo = t - rolling_window
        a_roll, b_roll = _ols(y[lo:t], x[lo:t])
        rolling_beta_oos.append(b_roll)
        rolling_pred.append(a_roll + b_roll * x[t])

        # State filtered through t-1: no look-ahead into today's y.
        dlm_pred.append(alpha_dlm[t - 1] + beta_dlm[t - 1] * x[t])

    actual = y[n_train:]
    preds = {
        "Static": np.asarray(static_pred),
        "Rolling": np.asarray(rolling_pred),
        "PyDLM": np.asarray(dlm_pred),
    }
    resid = {name: actual - p for name, p in preds.items()}

    oos_dates = dates[n_train:]
    resid_vol = {
        name: pd.Series(r).rolling(ROLLING_VOL_WINDOW).std().to_numpy()
        for name, r in resid.items()
    }

    log.info(
        "Hedge analysis %s~%s: %d days (%d train / %d test), discount %.2f, "
        "static beta %.4f",
        y_symbol.upper(), x_symbol.upper(), n_total, n_train, n_test,
        discount, beta_static,
    )

    def _clean(v):
        """NaN is not valid JSON; the rolling-vol warm-up legitimately has it."""
        return None if v is None or not np.isfinite(v) else float(v)

    return {
        "y_symbol": y_symbol.upper(),
        "x_symbol": x_symbol.upper(),
        "n_total": n_total,
        "n_train": n_train,
        "n_test": n_test,
        "first_date": dates[0].date().isoformat(),
        "last_date": dates[-1].date().isoformat(),
        "train_end": dates[n_train - 1].date().isoformat(),
        "discount": discount,
        "rolling_window": rolling_window,
        "test_fraction": test_fraction,
        "alpha_static": alpha_static,
        "beta_static": beta_static,
        "in_sample": [
            {"date": d.date().isoformat(), "beta_pydlm": _clean(b)}
            for d, b in zip(dates[:n_train], beta_dlm[:n_train])
        ],
        "oos": [
            {
                "date": d.date().isoformat(),
                "actual_price": float(np.exp(actual[i])),
                "static_price": float(np.exp(preds["Static"][i])),
                "rolling_price": float(np.exp(preds["Rolling"][i])),
                "pydlm_price": float(np.exp(preds["PyDLM"][i])),
                "beta_pydlm": _clean(beta_dlm[n_train + i - 1]),
                "beta_rolling": _clean(rolling_beta_oos[i]),
                "resid_static": _clean(resid["Static"][i]),
                "resid_rolling": _clean(resid["Rolling"][i]),
                "resid_pydlm": _clean(resid["PyDLM"][i]),
                "vol_static": _clean(resid_vol["Static"][i]),
                "vol_rolling": _clean(resid_vol["Rolling"][i]),
                "vol_pydlm": _clean(resid_vol["PyDLM"][i]),
            }
            for i, d in enumerate(oos_dates)
        ],
        "metrics": [{"model": name, **_metrics(r)} for name, r in resid.items()],
    }

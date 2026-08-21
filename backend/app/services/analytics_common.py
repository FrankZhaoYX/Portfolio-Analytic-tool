import pandas as pd


def build_daily_valuation(trades_df: pd.DataFrame, prices_df: pd.DataFrame) -> pd.DataFrame:
    """Build a daily portfolio valuation series from trades + EOD prices.

    Returns a DataFrame indexed by date with columns:
      - market_value: total portfolio market value as of that date's close
      - cash_flow: net investor cash flow that day (positive = buy/contribution, negative = sell/withdrawal)
    Used by both performance_service (TWR/MWR) and risk_service (return series).
    """
    if trades_df.empty:
        return pd.DataFrame(columns=["market_value", "cash_flow"])

    trades = trades_df.copy()
    trades["tradedate"] = pd.to_datetime(trades["tradedate"]).dt.normalize()
    trades["symbol"] = trades["symbol"].str.upper()

    prices = prices_df.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.normalize()
    prices["symbol"] = prices["symbol"].str.upper()

    start = trades["tradedate"].min()
    end = max(prices["date"].max(), trades["tradedate"].max())
    all_dates = pd.date_range(start, end, freq="D")

    price_wide = prices.pivot_table(index="date", columns="symbol", values="close")
    price_wide = price_wide.reindex(all_dates).ffill()

    qty_by_day = trades.groupby(["tradedate", "symbol"])["qty"].sum().unstack(fill_value=0.0)
    qty_by_day = qty_by_day.reindex(all_dates, fill_value=0.0)
    holdings = qty_by_day.cumsum()
    holdings = holdings.reindex(columns=price_wide.columns, fill_value=0.0)

    market_value = (holdings * price_wide.reindex(columns=holdings.columns)).sum(axis=1)

    trades["signed_cash_flow"] = trades["qty"] * trades["price"] + trades["fees"]
    cash_flow = trades.groupby("tradedate")["signed_cash_flow"].sum().reindex(all_dates, fill_value=0.0)

    result = pd.DataFrame({"market_value": market_value, "cash_flow": cash_flow})
    result.index.name = "date"
    return result


def daily_returns(valuation: pd.DataFrame) -> pd.Series:
    """Daily time-weighted subperiod returns, adjusting for cash flow distortion.

    r_t = (MV_t - CF_t - MV_{t-1}) / MV_{t-1}
    """
    mv = valuation["market_value"]
    cf = valuation["cash_flow"]
    prev_mv = mv.shift(1)
    returns = (mv - cf - prev_mv) / prev_mv.replace(0.0, pd.NA)
    return returns.dropna()

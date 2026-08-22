import dbservice_client as dbs
import pandas as pd

from app.db.tables import FUNDAMENTALS
from app.models.allocation import AllocationBreakdown, AllocationDimension, AllocationSlice
from app.services.positions_service import get_positions


def get_allocation(session: dbs.Session, dimension: AllocationDimension) -> AllocationBreakdown:
    positions = get_positions(session)
    if not positions:
        return AllocationBreakdown(dimension=dimension, slices=[])

    pos_df = pd.DataFrame([p.model_dump() for p in positions])

    if dimension == AllocationDimension.SYMBOL:
        merged = pos_df
        label_col = "symbol"
    else:
        symlist = ",".join(f"'{s}'" for s in pos_df["symbol"].unique())
        fundamentals_df = session.query_sql(
            query=(
                f"SELECT symbol, {dimension.value}, asofdate FROM {FUNDAMENTALS} "
                f"WHERE symbol IN ({symlist}) ORDER BY asofdate DESC"
            ),
            return_as="pandas",
        )
        if fundamentals_df.empty:
            fundamentals_df = pd.DataFrame(columns=["symbol", dimension.value, "asofdate"])
        else:
            fundamentals_df = fundamentals_df.drop_duplicates(subset="symbol", keep="first")
        merged = pos_df.merge(fundamentals_df, on="symbol", how="left")
        merged[dimension.value] = merged[dimension.value].fillna("Unknown")
        label_col = dimension.value

    grouped = merged.groupby(label_col)["market_value"].sum().sort_values(ascending=False)
    total = grouped.sum()

    slices = [
        AllocationSlice(
            label=str(label),
            market_value=float(value),
            weight_pct=float(value / total * 100.0) if total else 0.0,
        )
        for label, value in grouped.items()
    ]

    return AllocationBreakdown(dimension=dimension, slices=slices)

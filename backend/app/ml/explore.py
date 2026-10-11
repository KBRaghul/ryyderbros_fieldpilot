"""Quick look at the yield dataset: trend over time and which weather features matter."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "yield"

crop = sys.argv[1] if len(sys.argv) > 1 else "corn"
df = pd.read_csv(DATA_DIR / f"{crop}_county_dataset.csv")

print(f"{crop}: {len(df)} rows, {df['county'].nunique()} counties, {df['year'].min()} to {df['year'].max()}\n")
print("Yield summary:")
print(df["yield"].describe().round(1).to_string(), "\n")

print("Statewide average by year:")
yearly = df.groupby("year").agg(
    mean_yield=("yield", "mean"),
    counties=("yield", "size"),
    jul_balance=("jul_balance_in", "mean"),
    heat_days=("heat_days", "mean"),
).round(1)
print(yearly.to_string(), "\n")

slope, intercept = np.polyfit(df["year"], df["yield"], 1)
df["yield_anomaly"] = df["yield"] - (slope * df["year"] + intercept)
print(f"Trend: yields rise about {slope:.1f} per year\n")

features = ["season_rain_in", "season_balance_in", "jul_balance_in", "aug_balance_in",
            "summer_rain_in", "avg_summer_tmax_f", "gdd", "heat_days", "max_dry_spell"]
print("Correlation of each weather feature with yield above or below trend:")
print(df[features + ["yield_anomaly"]].corr()["yield_anomaly"].drop("yield_anomaly")
      .sort_values().round(2).to_string())
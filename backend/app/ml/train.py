"""Train and compare yield models with leave-one-year-out testing.

Prediction = statewide trend + county's usual level + weather adjustment.

Usage:
    python -m app.ml.train corn
    python -m app.ml.train cotton
"""
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "yield"
MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

# One non-overlapping feature per factor, so the effects stay explainable.
FEATURES = {
    "corn": ["avg_summer_tmax_f", "summer_rain_in", "max_dry_spell", "lat", "lon"],
    "cotton": ["avg_summer_tmax_f", "aug_balance_in", "summer_rain_in", "max_dry_spell", "lat", "lon"],
}
SHRINK = 5  # counties with few years get pulled toward the statewide trend


def fit_trend(train):
    """Statewide yield trend over time."""
    slope, intercept = np.polyfit(train["year"], train["yield"], 1)
    return slope, intercept


def county_effects(train, slope, intercept):
    """How far each county usually sits above or below the trend, shrunk for small samples."""
    resid = train["yield"] - (slope * train["year"] + intercept)
    g = resid.groupby(train["geoid"]).agg(["mean", "size"])
    return (g["mean"] * g["size"] / (g["size"] + SHRINK)).to_dict()


def add_baseline(df, slope, intercept, effects):
    out = df.copy()
    out["baseline"] = slope * out["year"] + intercept + out["geoid"].map(effects).fillna(0.0)
    return out


def make_models():
    return {
        "baseline": None,
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "xgboost": XGBRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
        ),
    }


def leave_one_year_out(df, features):
    """Hide each year in turn, train on the rest, predict the hidden year."""
    preds = {name: pd.Series(np.nan, index=df.index) for name in make_models()}
    for year in sorted(df["year"].unique()):
        train, test = df[df["year"] != year], df[df["year"] == year]
        slope, intercept = fit_trend(train)
        effects = county_effects(train, slope, intercept)
        tr = add_baseline(train, slope, intercept, effects)
        te = add_baseline(test, slope, intercept, effects)
        for name, model in make_models().items():
            if model is None:
                preds[name].loc[te.index] = te["baseline"]
            else:
                model.fit(tr[features], tr["yield"] - tr["baseline"])
                preds[name].loc[te.index] = te["baseline"] + model.predict(te[features])
    return preds


def score(y, p):
    err = p - y
    return {
        "MAE": float(np.abs(err).mean()),
        "RMSE": float(np.sqrt((err ** 2).mean())),
        "R2": float(1 - (err ** 2).sum() / ((y - y.mean()) ** 2).sum()),
    }


def main(crop):
    df = pd.read_csv(DATA_DIR / f"{crop}_county_dataset.csv", dtype={"geoid": str})
    unit = "bu/acre" if crop == "corn" else "lb/acre"
    features = FEATURES[crop]

    preds = leave_one_year_out(df, features)
    results = {name: score(df["yield"], p) for name, p in preds.items()}
    print(f"{crop}: leave-one-year-out ({len(df)} rows, {df['year'].nunique()} years)")
    for name, s in results.items():
        print(f"  {name:<9} MAE {s['MAE']:6.1f} {unit}   RMSE {s['RMSE']:6.1f}   R2 {s['R2']:.2f}")

    best = min(results, key=lambda n: results[n]["MAE"])
    resid = df["yield"] - preds[best]
    lo, hi = np.percentile(resid, [10, 90])

    slope, intercept = fit_trend(df)
    effects = county_effects(df, slope, intercept)
    full = add_baseline(df, slope, intercept, effects)
    model = make_models()[best]
    if model is not None:
        model.fit(full[features], full["yield"] - full["baseline"])

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out = MODEL_DIR / f"{crop}_yield.joblib"
    joblib.dump({
        "crop": crop, "unit": unit, "model_name": best, "model": model,
        "features": features, "trend": (float(slope), float(intercept)),
        "county_effects": effects, "interval": (float(lo), float(hi)), "cv": results,
    }, out)

    print(f"\n  winner: {best}  ->  {out}")
    print(f"  80% range: prediction {lo:+.0f} to {hi:+.0f} {unit}")
    if best == "xgboost":
        ranked = sorted(zip(features, model.feature_importances_), key=lambda x: -x[1])
        print("  most important features:", ", ".join(f"{f} ({v:.2f})" for f, v in ranked[:5]))
    elif best == "ridge":
        coefs = sorted(zip(features, model[-1].coef_), key=lambda x: -abs(x[1]))
        print("  strongest effects (per 1 std):", ", ".join(f"{f} ({v:+.1f})" for f, v in coefs))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "corn")
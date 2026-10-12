"""Yield estimate for any field: county trend + county level + weather adjustment.

Usage:
    python -m app.ml.predict colbert_corn_1
"""
import json
import sys
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import httpx
import joblib
import pandas as pd
from shapely.geometry import shape

from app.ml.build_dataset import power_daily, season_features
from app.tools.sentinel import load_field

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "yield"
GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
LABELS = {
    "avg_summer_tmax_f": "summer heat",
    "summer_rain_in": "summer rainfall",
    "max_dry_spell": "longest dry spell",
    "aug_balance_in": "August water balance",
}


@lru_cache
def load_model(crop):
    return joblib.load(MODEL_DIR / f"{crop}_yield.joblib")


def find_county(lat, lon):
    """County GEOID and name for a point, from the Census geocoder."""
    params = {
        "x": lon, "y": lat,
        "benchmark": "Public_AR_Current", "vintage": "Current_Current",
        "layers": "Counties", "format": "json",
    }
    r = httpx.get(GEOCODER_URL, params=params, timeout=30)
    r.raise_for_status()
    county = r.json()["result"]["geographies"]["Counties"][0]
    return county["GEOID"], county["NAME"]


def weather_drivers(bundle, X):
    """How much each weather factor moved the estimate, in yield units."""
    if bundle["model_name"] != "ridge":
        return []
    scaler, ridge = bundle["model"][0], bundle["model"][-1]
    values = X.iloc[0].values
    effects = ridge.coef_ * (values - scaler.mean_) / scaler.scale_
    drivers = [
        {"factor": LABELS[f], "feature": f, "value": round(float(v), 1), "effect": round(float(e), 1)}
        for f, v, e in zip(bundle["features"], values, effects) if f in LABELS
    ]
    return sorted(drivers, key=lambda d: -abs(d["effect"]))


def nass_reported(crop, geoid, year):
    """USDA's reported county yield for that year, if it exists in the dataset."""
    path = DATA_DIR / f"{crop}_county_dataset.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"geoid": str})
    row = df[(df["geoid"] == geoid) & (df["year"] == year)]
    return float(row["yield"].iloc[0]) if len(row) else None


def predict_yield(geometry, crop, year):
    """Yield estimate with an 80% range and the weather factors behind it."""
    bundle = load_model(crop)
    c = shape(geometry).centroid
    lat, lon = round(c.y, 4), round(c.x, 4)
    geoid, county = find_county(lat, lon)

    end = min(date(year, 12, 31), date.today() - timedelta(days=3))
    days = power_daily(lat, lon, f"{year}0101", end.strftime("%Y%m%d"))
    feats = season_features(days, crop, year)
    if feats is None:
        raise ValueError(f"Not enough {year} weather yet for a {crop} season estimate")
    feats.update({"lat": lat, "lon": lon})
    X = pd.DataFrame([feats])[bundle["features"]]

    slope, intercept = bundle["trend"]
    trend = slope * year + intercept
    county_level = bundle["county_effects"].get(geoid, 0.0)
    adjustment = float(bundle["model"].predict(X)[0]) if bundle["model"] is not None else 0.0
    estimate = trend + county_level + adjustment
    lo, hi = bundle["interval"]

    return {
        "crop": crop,
        "year": year,
        "unit": bundle["unit"],
        "county": county,
        "geoid": geoid,
        "estimate": round(estimate),
        "range": [round(estimate + lo), round(estimate + hi)],
        "county_typical": round(trend + county_level),
        "weather_adjustment": round(adjustment),
        "drivers": weather_drivers(bundle, X),
        "nass_reported_county_yield": nass_reported(crop, geoid, year),
        "model": {
            "name": bundle["model_name"],
            "cv_mae": round(bundle["cv"][bundle["model_name"]]["MAE"], 1),
        },
        "note": "County-level estimate from weather at the field's location. "
                "Field-specific conditions (zones, soil, management) are not included.",
    }


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "colbert_corn_1"
    field = load_field(name)
    props = field["properties"]
    result = predict_yield(field["geometry"], props["crop"], props.get("year", 2025))
    u = result["unit"]
    print(f"{name}: {result['county']}, {result['crop']} {result['year']}")
    print(f"  estimate {result['estimate']} {u}  (80% range {result['range'][0]} to {result['range'][1]})")
    print(f"  county typical {result['county_typical']} {u}, weather adjustment {result['weather_adjustment']:+d} {u}")
    for d in result["drivers"]:
        print(f"    {d['factor']:<22} {d['value']:>7}  ->  {d['effect']:+.1f} {u}")
    if result["nass_reported_county_yield"] is not None:
        print(f"  USDA reported county yield: {result['nass_reported_county_yield']} {u}")
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
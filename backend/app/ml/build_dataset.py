"""Build an Alabama county-year dataset: NASS county yields + growing season weather features.

Weather comes from NASA POWER (free, long daily records per request).
ET0 is estimated with the Hargreaves method from daily max/min temperature.

Usage:
    python -m app.ml.build_dataset corn
    python -m app.ml.build_dataset cotton
"""
import csv
import io
import json
import math
import os
import sys
import time
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx

from app.tools.weather import (
    CROP_SEASON, HEAT_STRESS_F, c_to_f, growing_degree_days, longest_dry_spell, mm_to_in,
)

NASS_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2023_Gazetteer/2023_Gaz_counties_national.zip"
)
YIELD_ITEM = {
    "corn": "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE",
    "cotton": "COTTON, UPLAND - YIELD, MEASURED IN LB / ACRE",
}
START_YEAR, END_YEAR = 2000, 2025
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "yield"
CACHE_DIR = OUT_DIR / "weather_cache"


def nass_county_yields(crop):
    """County yields for Alabama from USDA NASS Quick Stats."""
    params = {
        "key": os.environ["NASS_API_KEY"],
        "source_desc": "SURVEY",
        "agg_level_desc": "COUNTY",
        "state_alpha": "AL",
        "short_desc": YIELD_ITEM[crop],
        "year__GE": START_YEAR,
        "format": "JSON",
    }
    r = httpx.get(NASS_URL, params=params, timeout=120)
    r.raise_for_status()
    rows = []
    for d in r.json()["data"]:
        if d["county_code"] in ("", "998"):      # 998 = "other (combined) counties"
            continue
        try:
            value = float(d["Value"].replace(",", ""))
        except ValueError:                        # suppressed values like "(D)"
            continue
        rows.append({
            "geoid": d["state_fips_code"] + d["county_code"],
            "county": d["county_name"].title(),
            "year": int(d["year"]),
            "yield": value,
        })
    return rows


def county_centroids():
    """Alabama county centroids (lat, lon) from the Census gazetteer file."""
    r = httpx.get(GAZETTEER_URL, timeout=120, follow_redirects=True)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        text = z.read(z.namelist()[0]).decode("latin-1")
    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        row = {k.strip(): v.strip() for k, v in row.items()}
        if row["USPS"] == "AL":
            out[row["GEOID"]] = (float(row["INTPTLAT"]), float(row["INTPTLONG"]))
    return out


def extraterrestrial_radiation(lat_deg, doy):
    """Top-of-atmosphere radiation Ra in MJ/m2/day (FAO-56 equation 21)."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(-math.tan(phi) * math.tan(delta))
    return (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws)
    )


def hargreaves_et0_mm(tmax_c, tmin_c, ra):
    """Reference evapotranspiration in mm/day from temperature (Hargreaves-Samani)."""
    tmean = (tmax_c + tmin_c) / 2
    return max(0.0023 * 0.408 * ra * (tmean + 17.8) * math.sqrt(max(tmax_c - tmin_c, 0)), 0)


def fetch_power_daily(geoid, lat, lon):
    """Daily weather for a county from NASA POWER, cached to disk."""
    cache = CACHE_DIR / f"{geoid}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    params = {
        "parameters": "T2M_MAX,T2M_MIN,PRECTOTCORR",
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": f"{START_YEAR}0101",
        "end": f"{END_YEAR}1231",
        "format": "JSON",
    }
    for _ in range(5):
        r = httpx.get(POWER_URL, params=params, timeout=180)
        if r.status_code == 429:
            print("    rate limited, waiting 60s")
            time.sleep(60)
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError("NASA POWER kept rate limiting, try again later")

    p = r.json()["properties"]["parameter"]
    days = []
    for key, tmax in p["T2M_MAX"].items():
        tmin, rain = p["T2M_MIN"][key], p["PRECTOTCORR"][key]
        if -999 in (tmax, tmin, rain):           # missing values
            continue
        d = date(int(key[:4]), int(key[4:6]), int(key[6:]))
        et0 = hargreaves_et0_mm(tmax, tmin, extraterrestrial_radiation(lat, d.timetuple().tm_yday))
        days.append({
            "date": d.isoformat(),
            "tmax_f": c_to_f(tmax),
            "tmin_f": c_to_f(tmin),
            "rain_in": mm_to_in(rain),
            "et0_in": mm_to_in(et0),
        })
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(days))
    return days


def season_features(days, crop, year):
    """Weather features for one county and one growing season."""
    lo, hi = CROP_SEASON[crop]
    season = [d for d in days if f"{year}-{lo}" <= d["date"] <= f"{year}-{hi}"]
    if len(season) < 100:
        return None

    def month(m):
        return [d for d in season if d["date"][5:7] == m]

    def balance(ds):
        return sum(d["rain_in"] - d["et0_in"] for d in ds)

    summer = month("06") + month("07") + month("08")
    return {
        "season_rain_in": round(sum(d["rain_in"] for d in season), 2),
        "season_balance_in": round(balance(season), 2),
        "jul_balance_in": round(balance(month("07")), 2),
        "aug_balance_in": round(balance(month("08")), 2),
        "summer_rain_in": round(sum(d["rain_in"] for d in summer), 2),
        "avg_summer_tmax_f": round(sum(d["tmax_f"] for d in summer) / len(summer), 1),
        "gdd": round(sum(growing_degree_days(d, crop) for d in season)),
        "heat_days": sum(d["tmax_f"] >= HEAT_STRESS_F for d in season),
        "max_dry_spell": longest_dry_spell(season),
    }


def build(crop):
    t0 = time.time()
    yields = nass_county_yields(crop)
    print(f"{crop}: {len(yields)} county-year yields from NASS")
    centroids = county_centroids()

    by_county = defaultdict(list)
    for y in yields:
        by_county[y["geoid"]].append(y)

    rows = []
    for i, (geoid, recs) in enumerate(sorted(by_county.items()), 1):
        if geoid not in centroids:
            continue
        lat, lon = centroids[geoid]
        cached = (CACHE_DIR / f"{geoid}.json").exists()
        days = fetch_power_daily(geoid, lat, lon)
        for rec in recs:
            feats = season_features(days, crop, rec["year"])
            if feats:
                rows.append({**rec, "lat": lat, "lon": lon, **feats})
        print(f"  [{i}/{len(by_county)}] {recs[0]['county']}: {len(recs)} years{' (cached)' if cached else ''}")
        if not cached:
            time.sleep(2)  # be polite to the free API

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{crop}_county_dataset.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["geoid"], r["year"])))
    print(f"{crop}: wrote {len(rows)} rows from {len(by_county)} counties in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "corn")
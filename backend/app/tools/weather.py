"""Weather for a field from Open-Meteo: growing season summary and short-term forecast."""
import json
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

import httpx
from shapely.geometry import shape

from app.tools.sentinel import load_field

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "et0_fao_evapotranspiration"]
CROP_SEASON = {"corn": ("04-01", "09-15"), "cotton": ("05-01", "11-15")}
HEAT_STRESS_F = 95     # days at or above this count as heat stress
DRY_DAY_IN = 0.1       # days with less rain than this count as dry
TIMEZONE = "America/Chicago"


def c_to_f(c):
    return c * 9 / 5 + 32


def mm_to_in(mm):
    return mm / 25.4


def field_point(geometry):
    """Field centroid as (lat, lon)."""
    c = shape(geometry).centroid
    return round(c.y, 4), round(c.x, 4)


def fetch_daily(lat, lon, start, end):
    """Observed daily weather in °F and inches. Recent days not yet in the archive are skipped."""
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "daily": ",".join(DAILY_VARS), "timezone": TIMEZONE,
    }
    r = httpx.get(ARCHIVE_URL, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    days = []
    for i, day in enumerate(d["time"]):
        tmax, tmin, rain, et0 = (d[v][i] for v in DAILY_VARS)
        if tmax is None or tmin is None:
            continue
        days.append({
            "date": day,
            "tmax_f": c_to_f(tmax),
            "tmin_f": c_to_f(tmin),
            "rain_in": mm_to_in(rain or 0),
            "et0_in": mm_to_in(et0 or 0),
        })
    return days


def growing_degree_days(day, crop):
    """Corn: base 50°F with temps capped at 50 to 86°F. Cotton: DD60."""
    if crop == "corn":
        hi = min(max(day["tmax_f"], 50), 86)
        lo = min(max(day["tmin_f"], 50), 86)
        return max((hi + lo) / 2 - 50, 0)
    return max((day["tmax_f"] + day["tmin_f"]) / 2 - 60, 0)


def longest_dry_spell(days):
    best = run = 0
    for d in days:
        run = run + 1 if d["rain_in"] < DRY_DAY_IN else 0
        best = max(best, run)
    return best


def season_summary(geometry, crop, year):
    """Season totals plus a monthly water balance for any field polygon."""
    lat, lon = field_point(geometry)
    lo, hi = CROP_SEASON[crop]
    end = min(date.fromisoformat(f"{year}-{hi}"), date.today() - timedelta(days=6))
    days = fetch_daily(lat, lon, f"{year}-{lo}", end.isoformat())
    if not days:
        raise ValueError("No weather data for this period")

    monthly = defaultdict(lambda: {"rain_in": 0.0, "et0_in": 0.0, "tmax": []})
    for d in days:
        m = monthly[d["date"][:7]]
        m["rain_in"] += d["rain_in"]
        m["et0_in"] += d["et0_in"]
        m["tmax"].append(d["tmax_f"])

    rain = sum(d["rain_in"] for d in days)
    et0 = sum(d["et0_in"] for d in days)
    return {
        "crop": crop,
        "location": {"lat": lat, "lon": lon},
        "period": {"start": days[0]["date"], "end": days[-1]["date"]},
        "total_rain_in": round(rain, 1),
        "total_et0_in": round(et0, 1),
        "water_balance_in": round(rain - et0, 1),
        "gdd": round(sum(growing_degree_days(d, crop) for d in days)),
        "gdd_method": "base 50F, capped 86F" if crop == "corn" else "DD60",
        "heat_stress_days": sum(d["tmax_f"] >= HEAT_STRESS_F for d in days),
        "longest_dry_spell_days": longest_dry_spell(days),
        "monthly": [
            {
                "month": k,
                "rain_in": round(v["rain_in"], 1),
                "et0_in": round(v["et0_in"], 1),
                "balance_in": round(v["rain_in"] - v["et0_in"], 1),
                "avg_tmax_f": round(sum(v["tmax"]) / len(v["tmax"]), 1),
            }
            for k, v in sorted(monthly.items())
        ],
    }


def forecast(geometry, days=7):
    """Daily forecast for the next few days."""
    lat, lon = field_point(geometry)
    params = {
        "latitude": lat, "longitude": lon, "forecast_days": days, "timezone": TIMEZONE,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
    }
    r = httpx.get(FORECAST_URL, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    return [
        {
            "date": d["time"][i],
            "tmax_f": round(c_to_f(d["temperature_2m_max"][i])),
            "tmin_f": round(c_to_f(d["temperature_2m_min"][i])),
            "rain_in": round(mm_to_in(d["precipitation_sum"][i] or 0), 2),
            "rain_chance_pct": d["precipitation_probability_max"][i],
        }
        for i in range(len(d["time"]))
    ]


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "lawrence_corn_1"
    field = load_field(name)
    props = field["properties"]
    t0 = time.time()
    summary = season_summary(field["geometry"], props["crop"], props.get("year", 2025))
    upcoming = forecast(field["geometry"])

    print(f"{name} ({summary['crop']}, {summary['period']['start']} to {summary['period']['end']}) "
          f"in {time.time() - t0:.1f}s")
    print(f"  rain {summary['total_rain_in']} in | ET0 {summary['total_et0_in']} in | "
          f"balance {summary['water_balance_in']} in")
    print(f"  GDD {summary['gdd']} ({summary['gdd_method']}) | heat stress days {summary['heat_stress_days']} | "
          f"longest dry spell {summary['longest_dry_spell_days']} days")
    for m in summary["monthly"]:
        print(f"    {m['month']}: rain {m['rain_in']:>4} in  ET0 {m['et0_in']:>4} in  "
              f"balance {m['balance_in']:>5} in  avg high {m['avg_tmax_f']}F")
    print("  next 7 days:")
    for f in upcoming:
        print(f"    {f['date']}: {f['tmin_f']}-{f['tmax_f']}F  rain {f['rain_in']} in ({f['rain_chance_pct']}%)")
    if "--json" in sys.argv:
        print(json.dumps({"season": summary, "forecast": upcoming}, indent=2))
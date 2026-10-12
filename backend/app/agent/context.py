"""Run every tool for a field once and cache the results as JSON.

Usage:
    python -m app.agent.context                  # all demo fields
    python -m app.agent.context colbert_corn_1   # one field
    python -m app.agent.context --refresh        # ignore the cache and recompute
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app.ml.predict import predict_yield
from app.tools.ndvi import ndvi_time_series
from app.tools.sentinel import FIELDS_DIR, load_field
from app.tools.soil import soil_summary
from app.tools.weather import forecast, season_summary
from app.tools.zones import CROP_SEASON, build_zones

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
CACHE_VERSION = 2  # bump this when the context format changes, to invalidate old files


def peak_in_season(rows, crop):
    """Highest NDVI inside the crop's growing window (ignores cover crops)."""
    lo, hi = CROP_SEASON[crop]
    in_season = [r for r in rows if lo <= r["date"][5:] <= hi]
    if not in_season:
        return None
    p = max(in_season, key=lambda r: r["ndvi"])
    return {"date": p["date"], "ndvi": p["ndvi"], "ndre": p["ndre"]}


def run_tools(field, year):
    """Run all tools in parallel. Failures are recorded, not raised."""
    geom, crop = field["geometry"], field["properties"]["crop"]
    jobs = {
        "ndvi_series": lambda: ndvi_time_series(field["name"], f"{year}-03-01", f"{year}-11-30"),
        "zones": lambda: build_zones(field["name"]),
        "weather": lambda: season_summary(geom, crop, year),
        "soil": lambda: soil_summary(geom),
        "yield": lambda: predict_yield(geom, crop, year),
    }

    def run(key):
        t0 = time.time()
        try:
            return key, jobs[key](), None, time.time() - t0
        except Exception as e:
            return key, None, f"{type(e).__name__}: {e}", time.time() - t0

    results, errors, timings = {}, {}, {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        for key, value, err, secs in pool.map(run, jobs):
            timings[key] = round(secs, 1)
            if err:
                errors[key] = err
            else:
                results[key] = value
    return results, errors, timings


def cache_path(name, year):
    return CACHE_DIR / f"{name}_{year}.json"


def field_context(name, refresh=False):
    """Everything the agent needs about a field's season, from cache when possible."""
    field = load_field(name)
    props = field["properties"]
    year = props.get("year", 2025)
    path = cache_path(name, year)

    if path.exists() and not refresh:
        ctx = json.loads(path.read_text())
        if ctx.get("version") == CACHE_VERSION:
            return ctx

    t0 = time.time()
    results, errors, timings = run_tools(field, year)
    series = results.get("ndvi_series") or []
    ctx = {
        "version": CACHE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "field": {**props, "name": name, "geometry": field["geometry"]},
        "season_year": year,
        "ndvi": {
            "peak": peak_in_season(series, props["crop"]),
            "clear_dates": len(series),
            "series": series,
        } if series else None,
        "zones": results.get("zones"),
        "weather": results.get("weather"),
        "soil": results.get("soil"),
        "yield": results.get("yield"),
        "errors": errors,
        "timings_s": timings,
        "total_s": round(time.time() - t0, 1),
    }
    if not errors:  # never cache a partial result
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ctx, indent=1))
    return ctx


def live_forecast(name):
    """7 day forecast, always fresh (never cached)."""
    return forecast(load_field(name)["geometry"])


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = args or sorted(p.stem for p in FIELDS_DIR.glob("*.geojson"))
    refresh = "--refresh" in sys.argv

    for name in names:
        year = load_field(name)["properties"].get("year", 2025)
        path = cache_path(name, year)
        was_cached = (not refresh and path.exists()
                      and json.loads(path.read_text()).get("version") == CACHE_VERSION)
        t0 = time.time()
        ctx = field_context(name, refresh=refresh)
        source = "cache" if was_cached else f"computed, tools {ctx['timings_s']}"
        print(f"{name}: {time.time() - t0:.1f}s ({source})")

        peak = ctx["ndvi"]["peak"] if ctx["ndvi"] else None
        if peak:
            print(f"  peak NDVI {peak['ndvi']} on {peak['date']}")
        if ctx["zones"]:
            low = next((f["properties"] for f in ctx["zones"]["features"]
                        if f["properties"]["zone"] == "low"), None)
            print(f"  low zone: {low['percent']}% {low['direction']}" if low else "  low zone: none")
        if ctx["yield"]:
            y = ctx["yield"]
            print(f"  yield {y['estimate']} {y['unit']} ({y['range'][0]} to {y['range'][1]})")
        if ctx["errors"]:
            print(f"  ERRORS: {ctx['errors']}")
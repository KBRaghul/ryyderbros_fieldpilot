"""Fields drawn by users: validate the shape, save it as a field file, and analyze it in the background.

A drawn field is saved as data/custom_fields/custom_<hash>.geojson. From then on it works like a
demo field: load_field finds it, and the cache, report, and chat build on it unchanged.

Usage:
    python -m app.tools.custom_fields path/to/shape.geojson corn
"""
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape
from shapely.validation import explain_validity

from app.agent.context import cache_path, field_context
from app.ml.predict import find_county
from app.tools.sentinel import CUSTOM_DIR

CROPS = ("corn", "cotton")
SEASON_YEAR = 2025          # same season as the demo fields
MIN_ACRES, MAX_ACRES = 5, 1000
MAX_POINTS = 200
ALABAMA_BOX = (-88.48, 30.14, -84.89, 35.01)   # lon/lat bounds, a quick check before the Census lookup
ALABAMA_FIPS = "01"
M2_PER_ACRE = 4046.8564224
DAILY_LIMIT = 3             # new analyses per visitor per day

# Is the drawn area a crop field? Measured from the satellite data, never guessed.
MIN_PEAK_NDVI = 0.4         # corn and cotton fields reach 0.7 or more at their peak
PARTIAL_BARE_PCT = 10       # this much bare ground at the peak: analyze, with a warning
MAX_BARE_PCT = 40           # more than this: not a field
EVERGREEN_MIN_NDVI = 0.5    # never below this all season: forest, lawn, or pasture, not a row crop
EVERGREEN_MIN_DATES = 8     # need enough clear dates to trust the season low
ID_RE = re.compile(r"^custom_[0-9a-f]{8}$")


class FieldError(ValueError):
    """A drawn field that cannot be analyzed. The message is shown to the user."""


def is_custom_id(name):
    return bool(ID_RE.match(name)) and (CUSTOM_DIR / f"{name}.geojson").exists()


def acres(geometry):
    """Area in acres, measured in an equal-area projection (USA Contiguous Albers)."""
    return shape(transform_geom("EPSG:4326", "EPSG:5070", geometry)).area / M2_PER_ACRE


def validate(geometry, crop):
    """Check a drawn shape and return the field properties, or raise FieldError."""
    if crop not in CROPS:
        raise FieldError("Choose corn or cotton.")
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise FieldError("Draw one closed field boundary.")
    try:
        poly = shape(geometry)
    except Exception:
        raise FieldError("The field boundary could not be read. Draw it again.")
    if len(poly.exterior.coords) - 1 > MAX_POINTS:
        raise FieldError(f"The boundary has too many corners. Use at most {MAX_POINTS}.")
    if not poly.is_valid:
        reason = explain_validity(poly).split("[")[0].strip().lower()
        raise FieldError(f"The boundary crosses itself ({reason}). Draw it again without crossing lines.")

    west, south, east, north = ALABAMA_BOX
    lon_min, lat_min, lon_max, lat_max = poly.bounds
    if lon_min < west or lon_max > east or lat_min < south or lat_max > north:
        raise FieldError("Draw a field in Alabama. The yield model covers Alabama counties only.")

    size = acres(geometry)
    if size < MIN_ACRES:
        raise FieldError(f"The field is {size:.1f} acres. Draw a field of at least {MIN_ACRES} acres.")
    if size > MAX_ACRES:
        raise FieldError(f"The field is {size:,.0f} acres. Draw a field of at most {MAX_ACRES:,} acres.")

    c = poly.centroid
    try:
        geoid, county = find_county(round(c.y, 4), round(c.x, 4))
    except Exception:
        raise FieldError("The county lookup is not available now. Try again in a few minutes.")
    if not geoid.startswith(ALABAMA_FIPS):
        raise FieldError("Draw a field in Alabama. The yield model covers Alabama counties only.")
    return {"crop": crop, "county": county.removesuffix(" County"), "year": SEASON_YEAR,
            "acres": round(size, 1)}


def field_id(geometry, crop):
    """The same shape and crop always get the same ID, so a redraw reuses the cache."""
    ring = [[round(x, 6), round(y, 6)] for x, y in shape(geometry).exterior.coords]
    key = json.dumps({"crop": crop, "ring": ring})
    return "custom_" + hashlib.sha256(key.encode()).hexdigest()[:8]


def save(geometry, props):
    fid = field_id(geometry, props["crop"])
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    feature = {"type": "Feature", "properties": {"name": fid, **props},
               "geometry": mapping(shape(geometry))}
    (CUSTOM_DIR / f"{fid}.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]}))
    return fid


def land_check(ctx):
    """Classify the boundary as a field, a partial field, or not a field.
    Returns {"verdict", "message", "bare_percent"}. The message is shown to the user."""
    crop = ctx["field"]["crop"]
    ndvi = ctx.get("ndvi") or {}
    peak = ndvi.get("peak")
    bare = (ctx.get("zones") or {}).get("bare_percent")
    result = {"verdict": "field", "message": None, "bare_percent": bare}
    redraw = f"Draw the boundary around a planted {crop} field."

    if not peak:
        return {**result, "verdict": "rejected",
                "message": "No clear satellite images were found for this area in the growing season."}
    if peak["ndvi"] < MIN_PEAK_NDVI:
        return {**result, "verdict": "rejected", "message": (
            f"This area does not look like a crop field. Its greenest point this season was "
            f"NDVI {peak['ndvi']:.2f}. Corn and cotton fields usually reach 0.7 or higher. {redraw}")}
    if bare is not None and bare > MAX_BARE_PCT:
        return {**result, "verdict": "rejected", "message": (
            f"About {bare:.0f}% of this boundary looks like buildings, pavement, water, or bare "
            f"ground at the crop's peak. {redraw}")}
    series = ndvi.get("series") or []
    if len(series) >= EVERGREEN_MIN_DATES and min(r["ndvi"] for r in series) >= EVERGREEN_MIN_NDVI:
        return {**result, "verdict": "rejected", "message": (
            "This area stays green all year, like a forest, lawn, or pasture. A corn or cotton "
            f"field is bare before planting and after harvest. {redraw}")}
    if bare is not None and bare >= PARTIAL_BARE_PCT:
        return {**result, "verdict": "partial", "message": (
            f"About {bare:.0f}% of this boundary looks like buildings, pavement, water, or bare "
            "ground. Those areas show as low zones. For more accurate zones, redraw around the planted area.")}
    return result


def discard(fid):
    """Remove a rejected field so it cannot be opened."""
    for path in (CUSTOM_DIR / f"{fid}.geojson", cache_path(fid, SEASON_YEAR)):
        path.unlink(missing_ok=True)


def is_ready(fid):
    """Analyzed and cached. field_context only caches complete results."""
    return cache_path(fid, SEASON_YEAR).exists()


# Background jobs: one analysis at a time, so one visitor cannot overload the server.
_pool = ThreadPoolExecutor(max_workers=1)
_lock = threading.RLock()
_jobs = {}      # field ID -> {"status", "error", "started"}
_usage = {}     # (visitor, date) -> analyses started
_rejected = {}  # field ID -> reason, so a redraw of a rejected shape is refused at once


def _reject(fid, message):
    discard(fid)
    with _lock:
        _rejected[fid] = message


def cached_verdict(fid):
    """Land check for an analysis saved earlier (before a restart, or before this check existed).
    Returns the check, or None if there is no saved analysis. A rejected field is discarded."""
    if not is_ready(fid):
        return None
    land = land_check(field_context(fid))
    if land["verdict"] == "rejected":
        _reject(fid, land["message"])
    return land


def _analyze(fid):
    try:
        ctx = field_context(fid)
        if ctx["errors"]:
            failed = ", ".join(sorted(ctx["errors"]))
            discard(fid)
            raise RuntimeError(f"Some field data could not be read ({failed}). Try again later.")
        land = land_check(ctx)
        if land["verdict"] == "rejected":
            _reject(fid, land["message"])
            raise RuntimeError(land["message"])
        status = {"status": "ready", "error": None, "warning": land["message"]}
    except Exception as e:
        msg = str(e) if isinstance(e, RuntimeError) else "The analysis failed. Try again later."
        status = {"status": "failed", "error": msg, "warning": None}
    with _lock:
        _jobs[fid].update(status)


def submit(geometry, crop, visitor):
    """Validate, save, and start the analysis. Returns (field ID, status)."""
    props = validate(geometry, crop)
    fid = field_id(geometry, crop)
    with _lock:
        if fid in _rejected:
            raise FieldError(_rejected[fid])
        job = _jobs.get(fid)
        if is_ready(fid):
            save(geometry, props)
            if cached_verdict(fid)["verdict"] == "rejected":
                raise FieldError(_rejected[fid])
            return fid, "ready"
        if job and job["status"] == "processing":
            return fid, "processing"
        key = (visitor, date.today().isoformat())
        if _usage.get(key, 0) >= DAILY_LIMIT:
            raise FieldError(f"You can analyze {DAILY_LIMIT} new fields per day. Try again tomorrow.")
        _usage[key] = _usage.get(key, 0) + 1
        save(geometry, props)
        _jobs[fid] = {"status": "processing", "error": None, "warning": None, "started": time.time()}
    _pool.submit(_analyze, fid)
    return fid, "processing"


def status(fid):
    """processing, ready, or failed (with a reason). None if the ID is unknown."""
    with _lock:
        job = dict(_jobs.get(fid) or {})
    if job:
        return {"id": fid, "status": job["status"], "error": job["error"], "warning": job["warning"]}
    land = cached_verdict(fid) if is_custom_id(fid) else None   # analyzed before a restart
    if land and land["verdict"] == "rejected":
        return {"id": fid, "status": "failed", "error": land["message"], "warning": None}
    if land:
        return {"id": fid, "status": "ready", "error": None, "warning": land["message"]}
    return None


if __name__ == "__main__":
    shape_file, crop = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "corn"
    data = json.loads(open(shape_file).read())
    geom = data["features"][0]["geometry"] if data.get("type") == "FeatureCollection" else data
    try:
        props = validate(geom, crop)
    except FieldError as e:
        sys.exit(f"Rejected: {e}")
    fid = save(geom, props)
    print(f"{fid}: {props}. Analyzing...")
    t0 = time.time()
    ctx = field_context(fid)
    print(f"done in {time.time() - t0:.0f}s, errors: {ctx['errors'] or 'none'}")
    print(f"land check: {land_check(ctx)}")

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


def is_ready(fid):
    """Analyzed and cached. field_context only caches complete results."""
    return cache_path(fid, SEASON_YEAR).exists()


# Background jobs: one analysis at a time, so one visitor cannot overload the server.
_pool = ThreadPoolExecutor(max_workers=1)
_lock = threading.Lock()
_jobs = {}      # field ID -> {"status", "error", "started"}
_usage = {}     # (visitor, date) -> analyses started


def _analyze(fid):
    try:
        ctx = field_context(fid)
        if ctx["errors"]:
            failed = ", ".join(sorted(ctx["errors"]))
            raise RuntimeError(f"Some field data could not be read ({failed}). Try again later.")
        status = {"status": "ready", "error": None}
    except Exception as e:
        msg = str(e) if isinstance(e, RuntimeError) else "The analysis failed. Try again later."
        status = {"status": "failed", "error": msg}
    with _lock:
        _jobs[fid].update(status)


def submit(geometry, crop, visitor):
    """Validate, save, and start the analysis. Returns (field ID, status)."""
    props = validate(geometry, crop)
    fid = field_id(geometry, crop)
    with _lock:
        job = _jobs.get(fid)
        if is_ready(fid):
            save(geometry, props)
            return fid, "ready"
        if job and job["status"] == "processing":
            return fid, "processing"
        key = (visitor, date.today().isoformat())
        if _usage.get(key, 0) >= DAILY_LIMIT:
            raise FieldError(f"You can analyze {DAILY_LIMIT} new fields per day. Try again tomorrow.")
        _usage[key] = _usage.get(key, 0) + 1
        save(geometry, props)
        _jobs[fid] = {"status": "processing", "error": None, "started": time.time()}
    _pool.submit(_analyze, fid)
    return fid, "processing"


def status(fid):
    """processing, ready, or failed (with a reason). None if the ID is unknown."""
    with _lock:
        job = dict(_jobs.get(fid) or {})
    if job:
        return {"id": fid, "status": job["status"], "error": job["error"]}
    if is_custom_id(fid) and is_ready(fid):
        return {"id": fid, "status": "ready", "error": None}   # analyzed before a restart
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

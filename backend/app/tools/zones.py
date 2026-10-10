"""Productivity zones (low / medium / high) for a field from peak-season NDVI or NDRE."""
import json
import math
import sys
import time
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes, sieve
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.tools.ndvi import CLEAR_SCL, GDAL_ENV, OFFSET, SCALE, ndvi_time_series, read_field_bands
from app.tools.sentinel import load_field, search_sentinel2

CROP_SEASON = {"corn": ("03-15", "09-15"), "cotton": ("05-01", "11-15")}
LOW_CUT, HIGH_CUT = 0.90, 1.05   # relative to the field's median index value
MIN_PIXELS = 5                    # merge specks under 5 pixels (0.05 ha)
SATURATION = 0.85                 # above this field median NDVI, use NDRE for zones
PEAK_WINDOW = 21                  # only use dates within this many days of the peak
ZONES = {1: ("low", "#d73027"), 2: ("medium", "#fee08b"), 3: ("high", "#1a9850")}
DIRECTIONS = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "zones"


def pick_peak_scenes(field, n=3):
    """The n clearest in-season scenes near peak NDVI, all from one tile."""
    props = field["properties"]
    lo, hi = CROP_SEASON[props["crop"]]
    year = props.get("year", 2025)
    start, end = f"{year}-{lo}", f"{year}-{hi}"

    rows = [r for r in ndvi_time_series(field["name"], start, end) if r["clear_fraction"] >= 0.95]

    scenes = {}
    for s in search_sentinel2(field["geometry"], start, end, max_cloud=60):
        if s["field_coverage"] >= 0.99 and (
            s["date"] not in scenes or s["cloud_cover"] < scenes[s["date"]]["cloud_cover"]
        ):
            scenes[s["date"]] = s

    ranked = sorted(rows, key=lambda r: r["ndvi"], reverse=True)
    if not ranked:
        return []

    peak = date.fromisoformat(ranked[0]["date"])
    tile = scenes[ranked[0]["date"]]["tile"]
    near = [
        r for r in ranked
        if abs((date.fromisoformat(r["date"]) - peak).days) <= PEAK_WINDOW
        and scenes[r["date"]]["tile"] == tile
    ]
    return [scenes[r["date"]] for r in near][:n]


def pixel_indices(scene, geometry):
    """Per-pixel NDVI and NDRE over the field, NaN where cloudy or outside."""
    bands, inside, transform, crs = read_field_bands(scene, geometry)
    clear = inside & np.isin(bands["SCL"], CLEAR_SCL) & (bands["B04"] > 0)
    red, red_edge, nir = ((bands[b] - OFFSET) / SCALE for b in ("B04", "B05", "B08"))
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
        ndre = (nir - red_edge) / (nir + red_edge)
    ndvi[~clear] = np.nan
    ndre[~clear] = np.nan
    return ndvi, ndre, inside, transform, crs


def direction(zone_geom, field_geom):
    """Rough compass position of a zone within the field."""
    dx = zone_geom.centroid.x - field_geom.centroid.x
    dy = zone_geom.centroid.y - field_geom.centroid.y
    if math.hypot(dx, dy) < 0.1 * math.sqrt(field_geom.area):
        return "center or scattered"
    angle = math.degrees(math.atan2(dy, dx))
    return DIRECTIONS[int(((angle + 22.5) % 360) // 45)]


def build_zones(name):
    """Classify a field into low / medium / high zones and return GeoJSON."""
    field = load_field(name)
    scenes = pick_peak_scenes(field)
    if not scenes:
        raise ValueError(f"No clear in-season scenes for {name}")

    ndvi_stack, ndre_stack = [], []
    with rasterio.Env(**GDAL_ENV):
        for s in scenes:
            ndvi, ndre, inside, transform, crs = pixel_indices(s, field["geometry"])
            ndvi_stack.append(ndvi)
            ndre_stack.append(ndre)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ndvi = np.nanmedian(np.stack(ndvi_stack), axis=0)
        ndre = np.nanmedian(np.stack(ndre_stack), axis=0)

    valid = inside & ~np.isnan(ndvi)
    index_used = "ndre" if np.median(ndvi[valid]) > SATURATION else "ndvi"
    index = ndre if index_used == "ndre" else ndvi
    median = float(np.median(index[valid]))

    zones = np.zeros(index.shape, dtype="uint8")
    zones[valid & (index < LOW_CUT * median)] = 1
    zones[valid & (index >= LOW_CUT * median) & (index <= HIGH_CUT * median)] = 2
    zones[valid & (index > HIGH_CUT * median)] = 3
    zones = sieve(zones, size=MIN_PIXELS, mask=valid)

    field_utm = shape(transform_geom("EPSG:4326", crs, field["geometry"]))
    pixel_area = abs(transform.a * transform.e)
    total = int((zones > 0).sum())

    features = []
    for value, (label, color) in ZONES.items():
        polys = [shape(g) for g, v in shapes(zones, mask=zones == value, transform=transform)]
        if not polys:
            continue
        geom = unary_union(polys)
        count = int((zones == value).sum())
        features.append({
            "type": "Feature",
            "properties": {
                "zone": label,
                "acres": round(count * pixel_area / 4046.86, 1),
                "percent": round(100 * count / total, 1),
                "mean_ndvi": round(float(np.nanmean(ndvi[zones == value])), 3),
                "mean_ndre": round(float(np.nanmean(ndre[zones == value])), 3),
                "direction": direction(geom, field_utm),
                "fill": color,
                "fill-opacity": 0.6,
            },
            "geometry": transform_geom(crs, "EPSG:4326", mapping(geom)),
        })

    return {
        "type": "FeatureCollection",
        "field": name,
        "crop": field["properties"]["crop"],
        "scene_dates": sorted(s["date"] for s in scenes),
        "index_used": index_used,
        "field_median": round(median, 3),
        "features": features,
    }


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "lawrence_corn_1"
    t0 = time.time()
    fc = build_zones(name)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"{name}: zones on {fc['index_used'].upper()} from {', '.join(fc['scene_dates'])} "
          f"in {time.time() - t0:.0f}s -> {out}")
    for f in fc["features"]:
        p = f["properties"]
        print(f"  {p['zone']:>6}: {p['percent']:5.1f}% ({p['acres']} ac)  "
              f"NDVI {p['mean_ndvi']}  NDRE {p['mean_ndre']}  {p['direction']}")
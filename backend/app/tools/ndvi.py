"""Cloud-masked NDVI and NDRE time series for a field from Sentinel-2 L2A."""
import csv
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import bounds as window_bounds, from_bounds
from shapely.geometry import shape
from rasterio.errors import NotGeoreferencedWarning

from app.tools.sentinel import load_field, search_sentinel2

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)

CLEAR_SCL = [4, 5]            # SCL classes: 4 = vegetation, 5 = bare soil
OFFSET, SCALE = 1000, 10000   # L2A reflectance scaling (all 2025 data)
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "timeseries"
GDAL_ENV = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MULTIRANGE": "YES"}


def read_field_bands(scene, geometry):
    """Read B04, B05, B08, SCL over the field on one aligned 10 m grid."""
    with rasterio.open(scene["assets"]["B04"]) as ref:
        geom = transform_geom("EPSG:4326", ref.crs, geometry)
        win = from_bounds(*shape(geom).bounds, ref.transform).round_offsets().round_lengths()
        transform = ref.window_transform(win)
        bounds = window_bounds(win, ref.transform)
        out_shape = (int(win.height), int(win.width))
        crs = ref.crs
    bands = {}
    for b in ("B04", "B05", "B08", "SCL"):
        with rasterio.open(scene["assets"][b]) as src:
            bands[b] = src.read(
                1, window=from_bounds(*bounds, src.transform),
                out_shape=out_shape, resampling=Resampling.nearest,
            ).astype("float32")
    inside = ~geometry_mask([geom], out_shape=out_shape, transform=transform)
    return bands, inside, transform, crs


def scene_indices(scene, geometry, min_clear=0.8):
    """Mean NDVI and NDRE over clear pixels, or None if the field is too cloudy."""
    bands, inside, _, _ = read_field_bands(scene, geometry)
    clear = inside & np.isin(bands["SCL"], CLEAR_SCL) & (bands["B04"] > 0)
    clear_frac = clear.sum() / max(inside.sum(), 1)
    if clear_frac < min_clear:
        return None
    red, red_edge, nir = ((bands[b][clear] - OFFSET) / SCALE for b in ("B04", "B05", "B08"))
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
        ndre = (nir - red_edge) / (nir + red_edge)
    return {
        "date": scene["date"],
        "ndvi": round(float(np.nanmean(ndvi)), 4),
        "ndre": round(float(np.nanmean(ndre)), 4),
        "clear_fraction": round(float(clear_frac), 2),
        "pixels": int(clear.sum()),
    }


def ndvi_time_series(field_name, start="2025-03-01", end="2025-11-30"):
    """Clean NDVI/NDRE series for a demo field over a season."""
    field = load_field(field_name)
    scenes = [s for s in search_sentinel2(field["geometry"], start, end, max_cloud=60)
              if s["field_coverage"] >= 0.99]
    best = {}
    for s in scenes:  # keep one scene per date, the least cloudy
        if s["date"] not in best or s["cloud_cover"] < best[s["date"]]["cloud_cover"]:
            best[s["date"]] = s

    def run(s):
        try:
            with rasterio.Env(**GDAL_ENV):
                return scene_indices(s, field["geometry"])
        except Exception as e:
            print(f"  skipped {s['date']}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(run, best.values()) if r]
    return sorted(rows, key=lambda r: r["date"])


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "lawrence_corn_1"
    t0 = time.time()
    rows = ndvi_time_series(name)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "ndvi", "ndre", "clear_fraction", "pixels"])
        writer.writeheader()
        writer.writerows(rows)
    season = {"corn": ("03-15", "09-15"), "cotton": ("05-01", "11-15")}
    crop = load_field(name)["properties"]["crop"]
    lo, hi = season[crop]
    in_season = [r for r in rows if lo <= r["date"][5:] <= hi]
    peak = max(in_season, key=lambda r: r["ndvi"]) if in_season else None
    print(f"{name}: {len(rows)} clear dates in {time.time() - t0:.0f}s -> {out}")
    if peak:
        print(f"  peak NDVI {peak['ndvi']} on {peak['date']}")
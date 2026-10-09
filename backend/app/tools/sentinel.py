"""Sentinel-2 L2A scene search via Microsoft Planetary Computer STAC."""
import json
import sys
import time
from pathlib import Path

import planetary_computer
import pystac_client
from shapely.geometry import shape

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
FIELDS_DIR = Path(__file__).resolve().parents[2] / "data" / "fields"

_catalog = None


def get_catalog():
    """Open the STAC catalog once and reuse it."""
    global _catalog
    if _catalog is None:
        _catalog = pystac_client.Client.open(
            STAC_URL, modifier=planetary_computer.sign_inplace
        )
    return _catalog


def load_field(name: str) -> dict:
    """Load a demo field from backend/data/fields/<name>.geojson."""
    data = json.loads((FIELDS_DIR / f"{name}.geojson").read_text())
    feature = data["features"][0]
    return {"name": name, "properties": feature["properties"], "geometry": feature["geometry"]}


def search_sentinel2(geometry: dict, start: str, end: str, max_cloud: float = 30) -> list[dict]:
    """Return Sentinel-2 scenes that overlap the field, sorted by date."""
    field = shape(geometry)
    search = get_catalog().search(
        collections=[COLLECTION],
        intersects=geometry,
        datetime=f"{start}/{end}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
    )
    scenes = []
    for item in search.items():
        coverage = field.intersection(shape(item.geometry)).area / field.area
        scenes.append({
            "id": item.id,
            "date": item.datetime.date().isoformat(),
            "cloud_cover": round(item.properties["eo:cloud_cover"], 1),
            "tile": item.properties.get("s2:mgrs_tile"),
            "field_coverage": round(coverage, 2),
            "assets": {b: item.assets[b].href for b in ("B04", "B05", "B08", "SCL") if b in item.assets},
        })
    return sorted(scenes, key=lambda s: s["date"])


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "lawrence_corn_1"
    field = load_field(name)
    t0 = time.time()
    scenes = search_sentinel2(field["geometry"], "2025-03-01", "2025-11-30")
    print(f"{name}: {len(scenes)} scenes in {time.time() - t0:.1f}s")
    for s in scenes[:5]:
        print(f"  {s['date']}  cloud {s['cloud_cover']}%  tile {s['tile']}  coverage {s['field_coverage']}")
"""Soil for a field from USDA SSURGO via the Soil Data Access (SDA) web service."""
import json
import sys
import time

import httpx
from shapely import wkt as shapely_wkt
from shapely.geometry import shape

from app.tools.sentinel import load_field

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest"
MIN_SHARE = 0.01   # ignore soil slivers under 1% of the field (boundary noise)


def sda_query(sql):
    """Run a SQL query against Soil Data Access and return rows as dicts."""
    r = httpx.post(SDA_URL, json={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=60)
    r.raise_for_status()
    table = r.json().get("Table", [])
    if not table:
        return []
    cols, rows = table[0], table[1:]
    return [dict(zip(cols, row)) for row in rows]


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def map_units_in_field(geometry):
    """Soil map units inside the field and the share of field area each covers."""
    wkt = shapely_wkt.dumps(shape(geometry), rounding_precision=6)
    aoi = f"geometry::STGeomFromText('{wkt}', 4326)"
    rows = sda_query(f"""
        SELECT mukey, SUM(mupolygongeo.STIntersection({aoi}).STArea()) AS area
        FROM mupolygon
        WHERE mupolygongeo.STIntersects({aoi}) = 1
        GROUP BY mukey
    """)
    total = sum(float(r["area"]) for r in rows)
    if not total:
        return {}
    return {r["mukey"]: float(r["area"]) / total for r in rows}


def map_unit_properties(mukeys):
    """Map unit summaries plus the surface horizon of each major component."""
    keys = ",".join(str(int(k)) for k in mukeys)
    agg = sda_query(f"""
        SELECT mukey, muname, aws0100wta, drclassdcd, hydgrpdcd, slopegradwta, niccdcd
        FROM muaggatt
        WHERE mukey IN ({keys})
    """)
    surface = sda_query(f"""
        SELECT c.mukey, c.compname, c.comppct_r,
               h.om_r, h.ph1to1h2o_r, h.sandtotal_r, h.claytotal_r, t.texdesc
        FROM component c
        JOIN chorizon h ON h.cokey = c.cokey AND h.hzdept_r = 0
        LEFT JOIN chtexturegrp t ON t.chkey = h.chkey AND t.rvindicator = 'Yes'
        WHERE c.mukey IN ({keys}) AND c.majcompflag = 'Yes'
    """)
    return {a["mukey"]: a for a in agg}, surface


def soil_summary(geometry):
    """Soil units in a field with water holding, drainage, and surface properties."""
    shares = {k: v for k, v in map_units_in_field(geometry).items() if v >= MIN_SHARE}
    if not shares:
        raise ValueError("No SSURGO soil data found for this field")
    agg, surface = map_unit_properties(shares)

    dominant = {}  # largest major component per map unit
    for s in surface:
        k = s["mukey"]
        if k not in dominant or (to_float(s["comppct_r"]) or 0) > (to_float(dominant[k]["comppct_r"]) or 0):
            dominant[k] = s

    units = []
    for k, share in sorted(shares.items(), key=lambda kv: -kv[1]):
        a, s = agg.get(k, {}), dominant.get(k, {})
        aws_cm = to_float(a.get("aws0100wta"))
        units.append({
            "mukey": k,
            "name": a.get("muname"),
            "percent": round(100 * share, 1),
            "available_water_in": round(aws_cm / 2.54, 1) if aws_cm is not None else None,
            "drainage": a.get("drclassdcd"),
            "hydrologic_group": a.get("hydgrpdcd"),
            "slope_pct": to_float(a.get("slopegradwta")),
            "capability_class": a.get("niccdcd"),
            "component": s.get("compname"),
            "surface_texture": s.get("texdesc"),
            "organic_matter_pct": to_float(s.get("om_r")),
            "ph": to_float(s.get("ph1to1h2o_r")),
            "sand_pct": to_float(s.get("sandtotal_r")),
            "clay_pct": to_float(s.get("claytotal_r")),
        })

    with_aws = [u for u in units if u["available_water_in"] is not None]
    weight = sum(u["percent"] for u in with_aws)
    field_aws = (
        round(sum(u["available_water_in"] * u["percent"] for u in with_aws) / weight, 1)
        if weight else None
    )
    return {
        "source": "USDA NRCS SSURGO",
        "field_available_water_in": field_aws,
        "dominant_soil": units[0]["name"],
        "dominant_drainage": units[0]["drainage"],
        "units": units,
    }


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "lawrence_corn_1"
    field = load_field(name)
    t0 = time.time()
    summary = soil_summary(field["geometry"])
    print(f"{name}: {len(summary['units'])} soil units in {time.time() - t0:.1f}s | "
          f"field available water {summary['field_available_water_in']} in (top 40 in)")
    for u in summary["units"]:
        print(f"  {u['percent']:5.1f}%  {u['name']}")
        print(f"         water {u['available_water_in']} in | {u['drainage']} | "
              f"texture {u['surface_texture']} | OM {u['organic_matter_pct']}% | pH {u['ph']} | "
              f"slope {u['slope_pct']}% | class {u['capability_class']}")
    if "--json" in sys.argv:
        print(json.dumps(summary, indent=2))
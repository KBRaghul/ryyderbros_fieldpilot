"""RyyderBros Field Pilot: AI crop scouting for Alabama corn and cotton fields."""
from datetime import date
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from shapely.geometry import shape
from streamlit_folium import st_folium

from app.agent.chat import ChatSession
from app.agent.context import field_context
from app.agent.report import generate_report
from app.tools.sentinel import FIELDS_DIR

st.set_page_config(
    page_title="RyyderBros Field Pilot | Crop Scouting",
    page_icon=str(Path(__file__).parent / "static" / "favicon.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Constants
SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
PANEL_HEIGHT = 560
MAX_QUESTIONS = 15  # chat questions per visitor session, protects the LLM budget

# Okabe-Ito palette: distinguishable for common types of color blindness
ZONE_COLORS = {"high": "#009E73", "medium": "#F0E442", "low": "#D55E00"}
CHART_COLORS = {"ndvi": "#0072B2", "ndre": "#E69F00", "peak": "#1A202C"}

TOOL_LABELS = {
    "get_field_overview": "Field overview",
    "get_crop_health": "Crop health",
    "get_problem_zones": "Productivity zones",
    "get_season_weather": "Season weather",
    "get_weather_forecast": "Forecast",
    "get_soil": "Soil survey",
    "get_yield_estimate": "Yield estimate",
}
DRIVER_UNITS = {"avg_summer_tmax_f": "°F", "summer_rain_in": "in",
                "max_dry_spell": "days", "aug_balance_in": "in"}

st.session_state.setdefault("questions_used", 0)

# Styles
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {
    --fp-green: #1F6F43; --fp-text: #1A202C; --fp-muted: #4A5568;
    --fp-border: #DDE3EA; --fp-bg: #F7F8FA;
}
html { font-size: 16px; }
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
section[data-testid="stSidebar"], div[data-testid="collapsedControl"] { display: none; }
.block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1440px; }

*:focus-visible { outline: 3px solid #2563EB !important; outline-offset: 2px; }

.st-key-topbar {
    background: linear-gradient(90deg, #1F6F43 0%, #3E8E3A 40%, #A8B83A 70%, #E9C46A 100%);
    padding: 18px 26px;
    margin-bottom: 6px;
}
.fp-brand { font-size: 1.35rem; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
.fp-tagline { font-size: 0.95rem; margin: 2px 0 0; }
.st-key-topbar .fp-brand { color: #FFFFFF; }
.st-key-topbar .fp-tagline { color: rgba(255, 255, 255, 0.9); }
.st-key-topbar label p { color: #1A202C; font-weight: 600; }

.fp-header {
    background: #FFFFFF; border: 1px solid var(--fp-border); border-left: 5px solid var(--fp-green);
    padding: 18px 22px; margin: 10px 0 16px;
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;
}
.fp-header h1 { font-size: 1.55rem; font-weight: 700; color: var(--fp-text); margin: 0; padding: 0; letter-spacing: -0.015em; }
.fp-header p { margin: 4px 0 0; color: var(--fp-muted); font-size: 0.95rem; }

.fp-chip {
    display: inline-block; padding: 4px 10px; font-size: 0.8rem;
    font-weight: 600; border: 1px solid; margin: 2px 0 2px 6px; white-space: nowrap;
}
.fp-chip-neutral { background: #F1F5F9; color: #334155; border-color: #CBD5E1; }
.fp-chip-ok { background: #E8F5EE; color: #14532D; border-color: #A7D7B8; }
.fp-chip-warn { background: #FEF6E7; color: #7A4B00; border-color: #F3D08B; }

div[data-testid="stMetric"] {
    background: #FFFFFF; border: 1px solid var(--fp-border); padding: 14px 18px;
}
div[data-testid="stMetricLabel"] p { font-size: 0.85rem; color: var(--fp-muted); font-weight: 500; }
div[data-testid="stMetricValue"] { font-weight: 700; color: var(--fp-text); font-size: 1.55rem; }

.stMarkdown h4 { font-size: 1rem; font-weight: 600; color: var(--fp-text); margin: 4px 0 8px; padding: 0; }
button[data-baseweb="tab"] p { font-weight: 600; font-size: 0.95rem; }
div[data-testid="stChatMessage"] { background: #FFFFFF; border: 1px solid var(--fp-border); }

.fp-legend { display: flex; gap: 20px; flex-wrap: wrap; font-size: 0.9rem; color: var(--fp-text); padding: 10px 4px 2px; }
.fp-swatch {
    display: inline-block; width: 14px; height: 14px; margin-right: 6px;
    vertical-align: -2px; border: 1px solid rgba(0,0,0,0.3);
}
.fp-driver {
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 9px 0; border-bottom: 1px solid var(--fp-border); font-size: 0.92rem; color: var(--fp-text);
}
.fp-footer { color: var(--fp-muted); font-size: 0.82rem; margin-top: 14px; }

*, *::before, *::after { border-radius: 2px !important; }
</style>
""", unsafe_allow_html=True)


# Data helpers
@st.cache_data(show_spinner="Loading field data...")
def load_context(name):
    return field_context(name)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_report(name):
    """Reports are cached for 24 hours per field, so repeat visitors do not use more LLM tokens."""
    return generate_report(name)


def field_label(name):
    county, crop, _ = name.split("_")
    return f"{county.title()} County {crop.title()}"


# Map, legend, chart, and drivers
def make_map(ctx):
    geom = shape(ctx["field"]["geometry"])
    minx, miny, maxx, maxy = geom.bounds
    m = folium.Map(location=[geom.centroid.y, geom.centroid.x], zoom_start=16, tiles=None)
    folium.TileLayer(tiles=SATELLITE_TILES, attr="Esri World Imagery", name="Satellite").add_to(m)
    if ctx.get("zones"):
        layer = {"type": "FeatureCollection", "features": []}
        for feat in ctx["zones"]["features"]:
            p = feat["properties"]
            layer["features"].append({
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": {"zone": p["zone"], "label": p["zone"].capitalize(),
                               "percent": p["percent"], "acres": p["acres"], "mean_ndvi": p["mean_ndvi"]},
            })
        folium.GeoJson(
            layer,
            name="Productivity zones",
            style_function=lambda feat: {
                "fillColor": ZONE_COLORS[feat["properties"]["zone"]],
                "color": ZONE_COLORS[feat["properties"]["zone"]],
                "weight": 1, "fillOpacity": 0.55,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["label", "percent", "acres", "mean_ndvi"],
                aliases=["Zone", "Share of field (%)", "Acres", "Mean NDVI"],
            ),
        ).add_to(m)
    folium.GeoJson(ctx["field"]["geometry"], name="Field boundary",
                   style_function=lambda _: {"color": "#FFFFFF", "weight": 2, "fillOpacity": 0}).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    return m


def zone_legend(ctx):
    feats = {z["properties"]["zone"]: z["properties"] for z in (ctx.get("zones") or {}).get("features", [])}
    items = []
    for zone in ("high", "medium", "low"):
        if zone in feats:
            p = feats[zone]
            items.append(f'<span><span class="fp-swatch" style="background:{ZONE_COLORS[zone]}"></span>'
                         f'<strong>{zone.capitalize()}</strong>: {p["percent"]}% ({p["acres"]} acres)</span>')
    return '<div class="fp-legend" role="list">' + "".join(items) + "</div>"


def ndvi_chart(ctx, height):
    ndvi = ctx.get("ndvi") or {}
    df = pd.DataFrame(ndvi.get("series", []))
    fig = go.Figure()
    if not df.empty:
        fig.add_scatter(x=df["date"], y=df["ndvi"], mode="lines+markers", name="NDVI",
                        line=dict(color=CHART_COLORS["ndvi"], width=2.5), marker=dict(symbol="circle", size=6))
        fig.add_scatter(x=df["date"], y=df["ndre"], mode="lines+markers", name="NDRE",
                        line=dict(color=CHART_COLORS["ndre"], width=2.5, dash="dash"),
                        marker=dict(symbol="square", size=6))
    peak = ndvi.get("peak")
    if peak:
        fig.add_scatter(x=[peak["date"]], y=[peak["ndvi"]], mode="markers", name="In-season peak",
                        marker=dict(size=13, symbol="diamond", color=CHART_COLORS["peak"]))
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10), template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="Date", yaxis_title="Index value",
        legend=dict(orientation="h", y=-0.28), font=dict(family="Inter, sans-serif", size=13, color="#1A202C"),
    )
    return fig


def drivers_html(y):
    rows = []
    for d in y.get("drivers", []):
        unit = DRIVER_UNITS.get(d.get("feature"), "")
        raised = d["effect"] > 0
        chip = "fp-chip-ok" if raised else "fp-chip-warn"
        verb = "Raised" if raised else "Lowered"
        rows.append(
            f'<div class="fp-driver"><span><strong>{d["factor"].capitalize()}</strong>: '
            f'{d["value"]} {unit} vs typical {d["typical"]} {unit}</span>'
            f'<span class="fp-chip {chip}">{verb} {abs(d["effect"])} {y["unit"]}</span></div>'
        )
    return "".join(rows)


# Top bar
fields = sorted(p.stem for p in FIELDS_DIR.glob("*.geojson"))
with st.container(key="topbar"):
    brand, picker = st.columns([3, 1], vertical_alignment="center")
    with brand:
        st.markdown('<p class="fp-brand">RyyderBros Field Pilot</p>'
                    '<p class="fp-tagline">AI crop scouting for Alabama corn and cotton</p>',
                    unsafe_allow_html=True)
    with picker:
        name = st.selectbox("Field", fields, format_func=field_label)

ctx = load_context(name)
f, y = ctx["field"], ctx.get("yield") or {}
county = y.get("county", f.get("county"))
weather = ctx.get("weather") or {}
peak = (ctx.get("ndvi") or {}).get("peak") or {}
zones = ctx.get("zones") or {"features": []}
low = next((z["properties"] for z in zones["features"] if z["properties"]["zone"] == "low"), None)
season_done = date.today() > date(ctx["season_year"], 11, 30)

# Field header
st.markdown(f"""
<div class="fp-header">
  <div>
    <h1>{field_label(name)}</h1>
    <p>{f['crop'].title()} · {county}, Alabama · {ctx['season_year']} season</p>
  </div>
  <div>
    <span class="fp-chip fp-chip-neutral">{'Season complete' if season_done else 'Season in progress'}</span>
    <span class="fp-chip fp-chip-neutral">{(ctx.get('ndvi') or {}).get('clear_dates', 0)} clear satellite dates</span>
    <span class="fp-chip fp-chip-ok">AI answers number-checked</span>
  </div>
</div>
""", unsafe_allow_html=True)

# Key numbers
c1, c2, c3, c4 = st.columns(4)
c1.metric("Peak NDVI", f"{peak['ndvi']:.2f}" if peak else "Not available",
          help=f"Highest in-season crop greenness, recorded on {peak.get('date', 'an unknown date')}")
c2.metric("Yield estimate", f"{y['estimate']} {y['unit']}" if y else "Not available",
          help=(f"County-level estimate based on weather. 80% range: {y['range'][0]} to "
                f"{y['range'][1]} {y['unit']}") if y else None)
c3.metric("Water balance", f"{weather.get('water_balance_in', 'n/a')} in",
          help="Growing season rain minus crop water demand. Negative means a deficit.")
c4.metric("Low-productivity zone", f"{low['percent']}%" if low else "None",
          help=f"Located: {low['direction']}" if low else "The field is uniform")

# Main: map left, tabbed panel right
left, right = st.columns([3, 2], gap="medium")

with left:
    with st.container(border=True):
        st.markdown("#### Productivity zones")
        st_folium(make_map(ctx), height=PANEL_HEIGHT, use_container_width=True, returned_objects=[])
        st.markdown(zone_legend(ctx), unsafe_allow_html=True)

with right:
    with st.container(border=True):
        tab_overview, tab_report, tab_chat, tab_data = st.tabs(
            ["Overview", "Report", "Ask Field Pilot", "Data"])

        with tab_overview:
            st.markdown("#### Crop health over the season")
            st.plotly_chart(ndvi_chart(ctx, 300), use_container_width=True)
            if y.get("drivers"):
                st.markdown("#### What moved the yield estimate")
                st.markdown(drivers_html(y), unsafe_allow_html=True)

        with tab_report:
            key = f"report_{name}"
            if st.button("Generate report", type="primary", use_container_width=True):
                with st.spinner("Writing and verifying the report..."):
                    st.session_state[key] = cached_report(name)
            r = st.session_state.get(key)
            with st.container(height=PANEL_HEIGHT - 40):
                if r:
                    if r["verified"]:
                        status = '<span class="fp-chip fp-chip-ok">Verified</span> Every number matches the field data.'
                    else:
                        problems = ", ".join(str(p) for p in r["unsupported_numbers"] + r["issues"])
                        status = f'<span class="fp-chip fp-chip-warn">Needs review</span> {problems}'
                    note = " The summary was completed automatically." if r.get("repaired") else ""
                    st.markdown(f'<p style="font-size:0.88rem;color:#4A5568;margin:0 0 8px">{status}{note}</p>',
                                unsafe_allow_html=True)
                    st.markdown(r["report"])
                else:
                    st.info("Generate a scouting report from this field's data. "
                            "Every number is checked against the data before the report is shown.")

        with tab_chat:
            skey = f"chat_{name}"
            if skey not in st.session_state:
                st.session_state[skey] = {"session": ChatSession(name), "history": []}
            chat = st.session_state[skey]

            with st.container(height=PANEL_HEIGHT - 110):
                if not chat["history"]:
                    st.caption("Ask a question about this field. Answers come from the field's data, "
                               "and every number is checked.")
                for msg in chat["history"]:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                        if msg.get("meta"):
                            st.caption(msg["meta"])

            limit_hit = st.session_state["questions_used"] >= MAX_QUESTIONS
            examples = ["Why is part of this field weak?", "Will it rain this week?",
                        "How did weather affect yield?"]
            cols = st.columns(len(examples))
            clicked = next((q for col, q in zip(cols, examples)
                            if col.button(q, key=f"ex_{name}_{q}", use_container_width=True,
                                          disabled=limit_hit)), None)
            if limit_hit:
                st.caption("You have reached the question limit for this demo session.")
                question = None
            else:
                question = st.chat_input("Ask a question about this field") or clicked

            if question:
                with st.spinner("Checking the field data..."):
                    ans = chat["session"].ask(question)
                st.session_state["questions_used"] += 1
                sources = ", ".join(TOOL_LABELS.get(t, t) for t in dict.fromkeys(ans["tools_used"])) or "None"
                meta = f"Sources: {sources} · {'Verified' if ans['verified'] else 'Needs review'}"
                chat["history"].append({"role": "user", "content": question})
                chat["history"].append({"role": "assistant", "content": ans["answer"], "meta": meta})
                st.rerun()

        with tab_data:
            with st.container(height=PANEL_HEIGHT):
                if weather.get("monthly"):
                    st.markdown("#### Weather by month")
                    wdf = pd.DataFrame(weather["monthly"]).rename(columns={
                        "month": "Month", "rain_in": "Rain (in)", "et0_in": "Crop water demand (in)",
                        "balance_in": "Water balance (in)", "avg_tmax_f": "Average high (°F)",
                    })
                    st.dataframe(wdf, hide_index=True, use_container_width=True)
                soil = ctx.get("soil") or {}
                if soil.get("units"):
                    st.markdown("#### Soil types")
                    sdf = pd.DataFrame(soil["units"])[
                        ["name", "percent", "available_water_in", "drainage", "ph", "capability_class"]
                    ].rename(columns={
                        "name": "Soil", "percent": "Share of field (%)", "available_water_in": "Available water (in)",
                        "drainage": "Drainage", "ph": "pH", "capability_class": "Capability class",
                    })
                    st.dataframe(sdf, hide_index=True, use_container_width=True)

st.markdown('<p class="fp-footer">Data sources: Sentinel-2 imagery via Microsoft Planetary Computer, '
            'Open-Meteo, USDA SSURGO, USDA NASS, and NASA POWER. Yield is a county-level estimate based on '
            'weather and is not a guarantee for an individual field.</p>', unsafe_allow_html=True)
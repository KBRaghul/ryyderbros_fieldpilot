"""FieldPilot: AI crop scouting for Alabama corn and cotton fields."""
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

st.set_page_config(page_title="FieldPilot", page_icon="🌱", layout="wide")

SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


@st.cache_data(show_spinner="Loading field data...")
def load_context(name):
    return field_context(name)


def field_label(name):
    county, crop, _ = name.split("_")
    return f"{county.title()} County {crop}"


def make_map(ctx):
    geom = shape(ctx["field"]["geometry"])
    minx, miny, maxx, maxy = geom.bounds
    m = folium.Map(location=[geom.centroid.y, geom.centroid.x], zoom_start=16, tiles=None)
    folium.TileLayer(tiles=SATELLITE_TILES, attr="Esri World Imagery", name="Satellite").add_to(m)
    if ctx.get("zones"):
        folium.GeoJson(
            ctx["zones"],
            name="Productivity zones",
            style_function=lambda feat: {
                "fillColor": feat["properties"]["fill"],
                "color": feat["properties"]["fill"],
                "weight": 1,
                "fillOpacity": 0.55,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["zone", "percent", "acres", "mean_ndvi"],
                aliases=["Zone", "% of field", "Acres", "Mean NDVI"],
            ),
        ).add_to(m)
    folium.GeoJson(
        ctx["field"]["geometry"],
        name="Field boundary",
        style_function=lambda _: {"color": "white", "weight": 2, "fillOpacity": 0},
    ).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    return m


def ndvi_chart(ctx):
    ndvi = ctx.get("ndvi") or {}
    df = pd.DataFrame(ndvi.get("series", []))
    fig = go.Figure()
    if not df.empty:
        fig.add_scatter(x=df["date"], y=df["ndvi"], mode="lines+markers", name="NDVI")
        fig.add_scatter(x=df["date"], y=df["ndre"], mode="lines+markers", name="NDRE")
    peak = ndvi.get("peak")
    if peak:
        fig.add_scatter(x=[peak["date"]], y=[peak["ndvi"]], mode="markers", name="In-season peak",
                        marker=dict(size=14, symbol="star"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="Index value", legend=dict(orientation="h", y=-0.15))
    return fig


# Sidebar
fields = sorted(p.stem for p in FIELDS_DIR.glob("*.geojson"))
with st.sidebar:
    st.title("🌱 FieldPilot")
    st.caption("AI crop scouting for Alabama corn and cotton")
    name = st.selectbox("Field", fields, format_func=field_label)
    ctx = load_context(name)
    f, y = ctx["field"], ctx.get("yield") or {}
    st.markdown(
        f"**Crop:** {f['crop'].title()}  \n"
        f"**County:** {y.get('county', f.get('county'))}  \n"
        f"**Season:** {ctx['season_year']}"
    )
    st.divider()
    st.caption("Data: Sentinel-2 via Microsoft Planetary Computer, Open-Meteo, USDA SSURGO, "
               "USDA NASS, NASA POWER. Yield is a county-level estimate based on weather.")

# Key numbers
st.header(field_label(name))
peak = (ctx.get("ndvi") or {}).get("peak") or {}
zones = ctx.get("zones") or {"features": []}
low = next((z["properties"] for z in zones["features"] if z["properties"]["zone"] == "low"), None)
weather = ctx.get("weather") or {}

c1, c2, c3, c4 = st.columns(4)
c1.metric("Peak NDVI", round(peak["ndvi"], 2) if peak else "n/a", help=f"In-season peak on {peak.get('date', '')}")
c2.metric("Yield estimate", f"{y['estimate']} {y['unit']}" if y else "n/a",
          help=f"County-level estimate, 80% range {y['range'][0]} to {y['range'][1]}" if y else None)
c3.metric("Season water balance", f"{weather.get('water_balance_in', 'n/a')} in",
          help="Rain minus crop water demand over the growing season")
c4.metric("Low zone", f"{low['percent']}% ({low['direction']})" if low else "None")

# Map and chart
left, right = st.columns([3, 2])
with left:
    st.subheader("Productivity zones")
    st_folium(make_map(ctx), height=420, use_container_width=True, returned_objects=[])
with right:
    st.subheader("Crop health over the season")
    st.plotly_chart(ndvi_chart(ctx), use_container_width=True)

# Tabs
tab_report, tab_chat, tab_data = st.tabs(["📋 Report", "💬 Ask FieldPilot", "📊 Data"])

with tab_report:
    key = f"report_{name}"
    if st.button("Generate report", type="primary"):
        with st.spinner("Writing and verifying the report..."):
            st.session_state[key] = generate_report(name)
    r = st.session_state.get(key)
    if r:
        badge = ("✅ Every number verified against the data" if r["verified"]
                 else f"⚠️ Unverified: {r['unsupported_numbers'] + r['issues']}")
        extra = " · summary repaired by code" if r.get("repaired") else ""
        st.caption(f"{badge} · {r['attempts']} draft(s){extra}")
        st.markdown(r["report"])
    else:
        st.info("Write a scouting report from this field's data. Every number is checked "
                "against the data before the report is shown.")

with tab_chat:
    skey = f"chat_{name}"
    if skey not in st.session_state:
        st.session_state[skey] = {"session": ChatSession(name), "history": []}
    chat = st.session_state[skey]

    for msg in chat["history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("meta"):
                st.caption(msg["meta"])

    question = st.chat_input("Ask about this field, like: Why is part of this field weak?")
    if question:
        chat["history"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Checking the data..."):
                ans = chat["session"].ask(question)
            meta = (f"Tools: {', '.join(ans['tools_used']) or 'none'} · "
                    f"{'✅ verified' if ans['verified'] else '⚠️ unverified'}")
            st.markdown(ans["answer"])
            st.caption(meta)
        chat["history"].append({"role": "assistant", "content": ans["answer"], "meta": meta})

with tab_data:
    if weather.get("monthly"):
        st.subheader("Weather by month")
        st.dataframe(pd.DataFrame(weather["monthly"]), hide_index=True, use_container_width=True)
    soil = ctx.get("soil") or {}
    if soil.get("units"):
        st.subheader("Soil types")
        cols = ["name", "percent", "available_water_in", "drainage", "ph", "capability_class"]
        st.dataframe(pd.DataFrame(soil["units"])[cols], hide_index=True, use_container_width=True)
    if y.get("drivers"):
        st.subheader("Yield drivers versus a typical season")
        st.dataframe(pd.DataFrame(y["drivers"])[["factor", "value", "typical", "effect"]],
                     hide_index=True, use_container_width=True)
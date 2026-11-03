import { useEffect, useState } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { cap } from "../utils";
import DrawControl from "./DrawControl";
import DrawPanel from "./DrawPanel";

const TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
// Okabe-Ito palette: distinguishable for common types of color blindness
export const ZONE_COLORS = {
  high: "#009E73",
  medium: "#F0E442",
  low: "#D55E00",
};

function FitToField({ geometry }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(L.geoJSON(geometry).getBounds());
  }, [geometry, map]);
  return null;
}

export default function FieldMap({ ctx, onCustomReady }) {
  const [drawing, setDrawing] = useState(false);
  const [shape, setShape] = useState(null);
  const [round, setRound] = useState(0);
  const zones = ctx.zones;
  const byZone = Object.fromEntries(
    (zones?.features || []).map((f) => [f.properties.zone, f.properties]),
  );

  return (
    <div className="panel">
      <div className="panel-head">
        <h2 className="panel-title">
          {drawing ? "Draw your field" : "Productivity zones"}
        </h2>
        {!drawing && (
          <button
            type="button"
            className="btn btn-quiet btn-small"
            onClick={() => setDrawing(true)}
          >
            Draw your own field
          </button>
        )}
      </div>
      <div className="map-box">
        <MapContainer
          center={[32.5, -86.5]}
          zoom={16}
          scrollWheelZoom={false}
          style={{ height: "100%", width: "100%" }}
        >
          <TileLayer url={TILES} attribution="Esri World Imagery" />
          {zones && (
            <GeoJSON
              key={`${ctx.field.name}-zones`}
              data={zones}
              style={(f) => ({
                color: ZONE_COLORS[f.properties.zone],
                fillColor: ZONE_COLORS[f.properties.zone],
                weight: 1,
                fillOpacity: 0.55,
              })}
              onEachFeature={(f, layer) =>
                layer.bindTooltip(
                  `Zone: ${cap(f.properties.zone)}<br>Share of field: ${f.properties.percent}%<br>Acres: ${f.properties.acres}<br>Mean NDVI: ${f.properties.mean_ndvi}`,
                )
              }
            />
          )}
          <GeoJSON
            key={`${ctx.field.name}-boundary`}
            data={ctx.field.geometry}
            style={{ color: "#FFFFFF", weight: 1.5, fillOpacity: 0 }}
          />
          <FitToField geometry={ctx.field.geometry} />
          {drawing && <DrawControl onShape={setShape} resetKey={round} />}
        </MapContainer>
      </div>
      {drawing ? (
        <DrawPanel
          shape={shape}
          onRedraw={() => setRound((r) => r + 1)}
          onCancel={() => setDrawing(false)}
          onReady={(field) => {
            setDrawing(false);
            onCustomReady(field);
          }}
        />
      ) : (
      <ul className="legend" aria-label="Zone key">
        {["high", "medium", "low"]
          .filter((z) => byZone[z])
          .map((z) => (
            <li key={z}>
              <span className="swatch" style={{ background: ZONE_COLORS[z] }} />
              {cap(z)}
              <span className="num">
                {byZone[z].percent}% · {byZone[z].acres} ac
              </span>
            </li>
          ))}
      </ul>
      )}
      <p className="map-note">
        Data sources: Sentinel-2 imagery via Microsoft Planetary Computer,
        Open-Meteo, USDA SSURGO, USDA NASS, and NASA POWER. Yield is a
        county-level estimate based on weather and is not a guarantee for an
        individual field.
      </p>
    </div>
  );
}

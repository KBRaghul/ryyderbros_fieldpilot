import { useEffect } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { cap } from "../utils";

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

export default function FieldMap({ ctx }) {
  const zones = ctx.zones;
  const byZone = Object.fromEntries(
    (zones?.features || []).map((f) => [f.properties.zone, f.properties]),
  );

  return (
    <div className="panel">
      <h2 className="panel-title">Productivity zones</h2>
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
            style={{ color: "#FFFFFF", weight: 2, fillOpacity: 0 }}
          />
          <FitToField geometry={ctx.field.geometry} />
        </MapContainer>
      </div>
      <div className="legend" role="list">
        {["high", "medium", "low"]
          .filter((z) => byZone[z])
          .map((z) => (
            <span key={z} role="listitem">
              <span className="swatch" style={{ background: ZONE_COLORS[z] }} />
              <strong>{cap(z)}</strong>: {byZone[z].percent}% ({byZone[z].acres}{" "}
              acres)
            </span>
          ))}
      </div>
      <p className="map-note">
        Data sources: Sentinel-2 imagery via Microsoft Planetary Computer,
        Open-Meteo, USDA SSURGO, USDA NASS, and NASA POWER. Yield is a
        county-level estimate based on weather and is not a guarantee for an
        individual field.
      </p>
    </div>
  );
}

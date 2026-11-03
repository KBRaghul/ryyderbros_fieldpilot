import { useEffect } from "react";
import { useMap } from "react-leaflet";
import "@geoman-io/leaflet-geoman-free";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";

const SHAPE_STYLE = { color: "#ffffff", weight: 2, fillColor: "#ffffff", fillOpacity: 0.15 };

// Polygon drawing on the existing map. Reports the shape as GeoJSON, or null when cleared.
// Changing `resetKey` clears the shape and starts a new drawing.
export default function DrawControl({ onShape, resetKey }) {
  const map = useMap();

  useEffect(() => {
    let layer = null;
    const report = () => onShape(layer ? layer.toGeoJSON().geometry : null);

    map.scrollWheelZoom.enable();
    map.pm.setGlobalOptions({
      allowSelfIntersection: false,
      snappable: false,
      pathOptions: SHAPE_STYLE,
      templineStyle: { color: "#ffffff" },
      hintlineStyle: { color: "#ffffff", dashArray: "4 4" },
    });
    map.pm.enableDraw("Polygon");

    const onCreate = (e) => {
      layer = e.layer;
      map.pm.disableDraw();
      layer.pm.enable();            // corners can be dragged to fix the outline
      layer.on("pm:edit", report);
      report();
    };
    map.on("pm:create", onCreate);

    return () => {
      map.off("pm:create", onCreate);
      map.pm.disableDraw();
      if (layer) map.removeLayer(layer);
      map.scrollWheelZoom.disable();
      onShape(null);
    };
  }, [map, onShape, resetKey]);

  return null;
}

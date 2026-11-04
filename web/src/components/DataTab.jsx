import { cap, signed, where } from "../utils";

const UNITS = {
  avg_summer_tmax_f: "°F",
  summer_rain_in: "in",
  max_dry_spell: "days",
  aug_balance_in: "in",
};
const ZONE_ORDER = { high: 0, medium: 1, low: 2 };
const MONTH = new Intl.DateTimeFormat("en-US", { month: "long" });

// One titled table. columns: [{ label, num }], rows: arrays of cells.
function Table({ title, note, columns, rows }) {
  if (!rows.length) return null;
  return (
    <section className="data-section">
      <h3 className="section-title data-title">{title}</h3>
      {note && <p className="data-note">{note}</p>}
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.label} scope="col" className={c.num ? "num" : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => (
                <td key={j} className={columns[j].num ? "num" : undefined}>
                  {cell ?? "n/a"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function monthlySatellite(series) {
  const months = {};
  for (const r of series || []) {
    const m = r.date.slice(0, 7);
    const best = months[m];
    if (!best || r.ndvi > best.ndvi) months[m] = r;
  }
  return Object.keys(months)
    .sort()
    .map((m) => {
      const r = months[m];
      const count = series.filter((x) => x.date.startsWith(m)).length;
      return [MONTH.format(new Date(`${m}-15T12:00:00`)), r.ndvi.toFixed(2), r.ndre.toFixed(2), count];
    });
}

export default function DataTab({ ctx }) {
  const zones = [...(ctx.zones?.features || [])]
    .map((f) => f.properties)
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone]);
  const zoneSoils = [...(ctx.zone_soils || [])].sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone]);
  const y = ctx.yield;
  const monthly = ctx.weather?.monthly || [];
  const soils = ctx.soil?.units || [];

  return (
    <div className="data-tab">
      <Table
        title="Productivity zones"
        note="From peak-season satellite images. Zones compare parts of this field with each other."
        columns={[
          { label: "Zone" },
          { label: "Share of field (%)", num: true },
          { label: "Acres", num: true },
          { label: "Mean NDVI", num: true },
          { label: "Location" },
        ]}
        rows={zones.map((z) => [cap(z.zone), z.percent, z.acres, z.mean_ndvi, cap(where(z.direction))])}
      />
      <Table
        title="Soils under each zone"
        columns={[
          { label: "Zone" },
          { label: "Soil" },
          { label: "Share of zone (%)", num: true },
          { label: "Share of field (%)", num: true },
          { label: "Pattern" },
        ]}
        rows={zoneSoils.flatMap((z) =>
          z.soils.map((s) => [cap(z.zone), s.soil, s.percent_of_zone, s.percent_of_field, cap(s.pattern)]),
        )}
      />
      {y && (
        <Table
          title="Yield estimate"
          note="A county-level estimate based on weather, not a prediction for this field."
          columns={[{ label: "Measure" }, { label: `Value (${y.unit})`, num: true }]}
          rows={[
            ["Estimate", y.estimate],
            ["80% range", `${y.range[0]} to ${y.range[1]}`],
            ["County typical", y.county_typical],
            ["Weather adjustment", (y.weather_adjustment > 0 ? "+" : "") + signed(y.weather_adjustment, 0)],
            ["USDA reported county yield", y.nass_reported_county_yield],
          ]}
        />
      )}
      {y?.drivers?.length > 0 && (
        <Table
          title="What moved the yield estimate"
          columns={[
            { label: "Factor" },
            { label: "This season", num: true },
            { label: "Typical season", num: true },
            { label: `Effect (${y.unit})`, num: true },
          ]}
          rows={y.drivers.map((d) => [
            cap(d.factor),
            `${d.value} ${UNITS[d.feature] || ""}`,
            `${d.typical} ${UNITS[d.feature] || ""}`,
            (d.effect > 0 ? "+" : "") + signed(d.effect),
          ])}
        />
      )}
      <Table
        title="Satellite readings by month"
        note="The greenest clear image in each month."
        columns={[
          { label: "Month" },
          { label: "Peak NDVI", num: true },
          { label: "NDRE that day", num: true },
          { label: "Clear images", num: true },
        ]}
        rows={monthlySatellite(ctx.ndvi?.series)}
      />
      <Table
        title="Weather by month"
        columns={[
          { label: "Month" },
          { label: "Rain (in)", num: true },
          { label: "Crop water demand (in)", num: true },
          { label: "Water balance (in)", num: true },
          { label: "Average high (°F)", num: true },
        ]}
        rows={monthly.map((m) => [m.month, m.rain_in, m.et0_in, m.balance_in, m.avg_tmax_f])}
      />
      <Table
        title="Soil types"
        note="From USDA soil survey maps, not a soil test in this field."
        columns={[
          { label: "Soil" },
          { label: "Share of field (%)", num: true },
          { label: "Available water (in)", num: true },
          { label: "Drainage" },
          { label: "pH", num: true },
          { label: "Capability class" },
        ]}
        rows={soils.map((u) => [u.name, u.percent, u.available_water_in, u.drainage, u.ph, u.capability_class])}
      />
    </div>
  );
}

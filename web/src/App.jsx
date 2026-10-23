import { useEffect, useState } from "react";
import { getField, getFields } from "./api";
import AskPanel from "./components/AskPanel";
import DataTab from "./components/DataTab";
import FieldMap from "./components/FieldMap";
import NdviChart from "./components/NdviChart";
import ReportPanel from "./components/ReportPanel";
import Footer from "./components/Footer";
import { cap } from "./utils";
import "./style.css";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "report", label: "Report" },
  { id: "ask", label: "Ask Field Pilot" },
  { id: "data", label: "Data" },
];
const UNITS = {
  avg_summer_tmax_f: "°F",
  summer_rain_in: "in",
  max_dry_spell: "days",
  aug_balance_in: "in",
};

function Metric({ label, value, help }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {help && <div className="metric-help">{help}</div>}
    </div>
  );
}

export default function App() {
  const [fields, setFields] = useState([]);
  const [fieldId, setFieldId] = useState("");
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState("");

  useEffect(() => {
    getFields()
      .then((fs) => {
        setFields(fs);
        setFieldId(fs[0]?.id || "");
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!fieldId) return;
    setData(null);
    setError("");
    getField(fieldId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [fieldId]);

  const ctx = data?.context;
  const y = ctx?.yield;
  const peak = ctx?.ndvi?.peak;
  const weather = ctx?.weather;
  const low = ctx?.zones?.features.find(
    (f) => f.properties.zone === "low",
  )?.properties;
  const year = ctx?.season_year;
  const seasonDone = year && new Date() > new Date(year, 10, 30);

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="brand">RyyderBros Field Pilot</p>
          <p className="tagline">
            AI crop scouting for Alabama corn and cotton
          </p>
        </div>
      </header>

      <section className="field-select" aria-label="Field selection">
        <label htmlFor="field">Select your field</label>
        <select
          id="field"
          className="select"
          value={fieldId}
          onChange={(e) => {
            setFieldId(e.target.value);
            setTab("overview");
          }}
        >
          {fields.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
      </section>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!ctx && !error && <p className="caption">Loading field data...</p>}

      {ctx && (
        <>
          <div className="field-header">
            <div>
              <h1>{data.label}</h1>
              <p>
                {cap(data.crop)} · {y?.county || data.county}, Alabama · {year}{" "}
                season
              </p>
            </div>
            <div>
              <span className="chip chip-neutral">
                {seasonDone ? "Season complete" : "Season in progress"}
              </span>
              <span className="chip chip-neutral">
                {ctx.ndvi?.clear_dates || 0} clear satellite dates
              </span>
              <span className="chip chip-ok">AI answers number-checked</span>
            </div>
          </div>

          <div className="metrics">
            <Metric
              label="Peak NDVI"
              value={peak ? peak.ndvi.toFixed(2) : "Not available"}
              help={peak && `In-season peak on ${peak.date}`}
            />
            <Metric
              label="Yield estimate"
              value={y ? `${y.estimate} ${y.unit}` : "Not available"}
              help={
                y && `County-level, 80% range ${y.range[0]} to ${y.range[1]}`
              }
            />
            <Metric
              label="Water balance"
              value={`${weather?.water_balance_in ?? "n/a"} in`}
              help="Season rain minus crop water demand"
            />
            <Metric
              label="Low-productivity zone"
              value={low ? `${low.percent}%` : "None"}
              help={low ? `Located: ${low.direction}` : "The field is uniform"}
            />
          </div>

          <div className="main">
            <FieldMap ctx={ctx} />

            <div className="panel">
              <div className="tabs" role="tablist" aria-label="Field views">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    role="tab"
                    id={`tab-${t.id}`}
                    aria-selected={tab === t.id}
                    aria-controls={`panel-${t.id}`}
                    onClick={() => setTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div
                role="tabpanel"
                id="panel-overview"
                aria-labelledby="tab-overview"
                hidden={tab !== "overview"}
              >
                <h3 className="panel-title">Crop health over the season</h3>
                <NdviChart ndvi={ctx.ndvi} />
                {y?.drivers?.length > 0 && (
                  <>
                    <h3 className="panel-title" style={{ marginTop: 16 }}>
                      What moved the yield estimate
                    </h3>
                    {y.drivers.map((d) => {
                      const raised = d.effect > 0;
                      return (
                        <div key={d.feature} className="driver">
                          <span>
                            <strong>{cap(d.factor)}</strong>: {d.value}{" "}
                            {UNITS[d.feature]} vs typical {d.typical}{" "}
                            {UNITS[d.feature]}
                          </span>
                          <span
                            className={`chip ${raised ? "chip-ok" : "chip-warn"}`}
                          >
                            {raised ? "Raised" : "Lowered"} {Math.abs(d.effect)}{" "}
                            {y.unit}
                          </span>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
              <div
                role="tabpanel"
                id="panel-report"
                aria-labelledby="tab-report"
                hidden={tab !== "report"}
              >
                <ReportPanel key={fieldId} fieldId={fieldId} />
              </div>
              <div
                role="tabpanel"
                id="panel-ask"
                aria-labelledby="tab-ask"
                hidden={tab !== "ask"}
              >
                <AskPanel key={fieldId} fieldId={fieldId} />
              </div>
              <div
                role="tabpanel"
                id="panel-data"
                aria-labelledby="tab-data"
                hidden={tab !== "data"}
              >
                <DataTab ctx={ctx} />
              </div>
            </div>
          </div>
        </>
      )}
      <Footer />
    </div>
  );
}

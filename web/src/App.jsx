import { useEffect, useState } from "react";
import { getField, getFields } from "./api";
import AskPanel from "./components/AskPanel";
import DataTab from "./components/DataTab";
import FieldMap from "./components/FieldMap";
import NdviChart from "./components/NdviChart";
import ReportPanel from "./components/ReportPanel";
import Footer from "./components/Footer";
import Checked from "./components/Checked";
import { cap, formatDate, signed, where } from "./utils";
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

function Metric({ label, value, unit, help }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
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
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <svg
              className="brand-mark"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M4 6.5 15.5 4 20 17.5 7 20Z" />
              <path d="M7.5 8.5 16 6.6M8.6 12.2l8.7-1.9M9.7 15.9l8.8-1.9" />
            </svg>
            <p className="brand-name">
              Field Pilot <span>by RyyderBros</span>
            </p>
            <p className="tagline">
              Satellite crop scouting for Alabama corn and cotton
            </p>
          </div>
          <div className="field-select">
            <label htmlFor="field">Field</label>
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
          </div>
        </div>
      </header>

      <main className="page">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!ctx && !error && <p className="caption">Loading field data</p>}

        {ctx && (
          <div className="content" key={fieldId}>
            <div className="field-header">
              <h1>{data.label}</h1>
              <p className="field-meta">
                <span>
                  {cap(data.crop)} · {y?.county || data.county}, Alabama ·{" "}
                  {year} season
                </span>
                <span className="mono">
                  {seasonDone ? "Season complete" : "Season in progress"} ·{" "}
                  {ctx.ndvi?.clear_dates || 0} clear satellite dates
                </span>
                <Checked>AI answers number-checked</Checked>
              </p>
            </div>

            <div className="metrics">
              <Metric
                label="Peak NDVI"
                value={peak ? peak.ndvi.toFixed(2) : "n/a"}
                help={peak && `In-season peak, ${formatDate(peak.date)}`}
              />
              <Metric
                label="Yield estimate"
                value={y ? y.estimate : "n/a"}
                unit={y && y.unit}
                help={
                  y && `County-level, 80% range ${y.range[0]} to ${y.range[1]}`
                }
              />
              <Metric
                label="Water balance"
                value={
                  weather?.water_balance_in != null
                    ? signed(weather.water_balance_in)
                    : "n/a"
                }
                unit="in"
                help="Season rain minus crop water demand"
              />
              <Metric
                label="Low-productivity zone"
                value={low ? low.percent : "None"}
                unit={low && "%"}
                help={
                  low
                    ? `Of the field, ${where(low.direction)}`
                    : "The crop grew evenly"
                }
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
                <h3 className="section-title">Crop health over the season</h3>
                <NdviChart ndvi={ctx.ndvi} />
                {y?.drivers?.length > 0 && (
                  <>
                    <h3 className="section-title">
                      What moved the yield estimate
                    </h3>
                    <ul className="drivers">
                      {y.drivers.map((d) => (
                        <li key={d.feature} className="driver">
                          <span>
                            {cap(d.factor)}
                            <span className="driver-detail">
                              {d.value} {UNITS[d.feature]} vs typical{" "}
                              {d.typical} {UNITS[d.feature]}
                            </span>
                          </span>
                          <span
                            className={`effect ${d.effect > 0 ? "up" : "down"}`}
                          >
                            {d.effect > 0 ? "+" : "\u2212"}
                            {Math.abs(d.effect)} {y.unit}
                          </span>
                        </li>
                      ))}
                    </ul>
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
          </div>
        )}
      </main>
      <Footer />
    </>
  );
}

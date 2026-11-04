import { useEffect, useRef, useState } from "react";
import { getCustomField, submitCustomField } from "../api";
import { estimatedPercent } from "../utils";
import AnalyzeOverlay from "./AnalyzeOverlay";

const POLL_MS = 4000;
const TICK_MS = 250;
const TIMEOUT_S = 300;
const FINISH_MS = 600; // show 100% briefly before the field opens

// Crop choice, Analyze, and progress for a field drawn on the map.
export default function DrawPanel({ shape, onRedraw, onCancel, onReady }) {
  const [crop, setCrop] = useState("corn");
  const [job, setJob] = useState(null); // { id, started, field }
  const [elapsed, setElapsed] = useState(0); // seconds, with decimals
  const [error, setError] = useState("");
  const readyRef = useRef(onReady);
  useEffect(() => {
    readyRef.current = onReady;
  }, [onReady]);

  useEffect(() => {
    if (!job) return;
    if (job.field) {
      // Ready: hold the bar at 100% for a moment, then open the field
      const done = setTimeout(() => {
        setJob(null);
        readyRef.current(job.field);
      }, FINISH_MS);
      return () => clearTimeout(done);
    }
    const tick = setInterval(() => {
      const secs = (Date.now() - job.started) / 1000;
      setElapsed(secs);
      if (secs > TIMEOUT_S) {
        setJob(null);
        setError("The analysis is taking too long. Try again later.");
      }
    }, TICK_MS);
    const poll = setInterval(async () => {
      try {
        const s = await getCustomField(job.id);
        if (s.status === "ready") {
          setJob((j) => j && { ...j, field: s.field });
        } else if (s.status === "failed") {
          setJob(null);
          setError(s.error);
        }
      } catch (e) {
        setJob(null);
        setError(e.message);
      }
    }, POLL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [job]);

  async function analyze() {
    setError("");
    try {
      const r = await submitCustomField({ geometry: shape, crop });
      if (r.status === "ready") onReady(r.field ?? (await getCustomField(r.id)).field);
      else {
        setElapsed(0);
        setJob({ id: r.id, started: Date.now() });
      }
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="draw-panel">
      {job && (
        <AnalyzeOverlay
          percent={job.field ? 100 : estimatedPercent(elapsed)}
          seconds={Math.floor(elapsed)}
        />
      )}
      <p className="draw-hint">
        {shape
          ? "Drag a corner to adjust the boundary."
          : "Click on the map to place each corner of your field. Click the first corner to finish."}
      </p>
      <div className="draw-row">
        <div className="segmented" role="radiogroup" aria-label="Crop">
          {["corn", "cotton"].map((c) => (
            <button
              key={c}
              type="button"
              role="radio"
              aria-checked={crop === c}
              onClick={() => setCrop(c)}
            >
              {c === "corn" ? "Corn" : "Cotton"}
            </button>
          ))}
        </div>
        <div className="draw-actions">
          <button type="button" className="btn btn-quiet" onClick={onCancel}>
            Cancel
          </button>
          {shape && (
            <button type="button" className="btn btn-quiet" onClick={onRedraw}>
              Redraw
            </button>
          )}
          <button
            type="button"
            className="btn"
            onClick={analyze}
            disabled={!shape}
          >
            Analyze
          </button>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

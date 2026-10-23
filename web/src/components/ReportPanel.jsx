import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { generateReport } from "../api";

export default function ReportPanel({ fieldId }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setLoading(true);
    setError("");
    try {
      setReport(await generateReport(fieldId));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const problems = report
    ? [...report.unsupported_numbers, ...report.issues].join(", ")
    : "";

  return (
    <div>
      <button type="button" className="btn" onClick={run} disabled={loading}>
        {loading ? "Writing and verifying the report..." : "Generate report"}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="scroll report" style={{ height: 480 }} aria-live="polite">
        {report ? (
          <>
            <p className="status-line">
              {report.verified ? (
                <>
                  <span className="chip chip-ok" style={{ marginLeft: 0 }}>
                    Verified
                  </span>{" "}
                  Every number matches the field data.
                </>
              ) : (
                <>
                  <span className="chip chip-warn" style={{ marginLeft: 0 }}>
                    Needs review
                  </span>{" "}
                  {problems}
                </>
              )}
              {report.repaired && " The summary was completed automatically."}
            </p>
            <ReactMarkdown>{report.report}</ReactMarkdown>
          </>
        ) : (
          <p className="caption" style={{ margin: 0 }}>
            Generate a scouting report from this field's data. Every number is
            checked against the data before the report is shown.
          </p>
        )}
      </div>
    </div>
  );
}

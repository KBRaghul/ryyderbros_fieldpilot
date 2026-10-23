import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { askQuestion } from "../api";

const EXAMPLES = [
  "Why is part of this field weak?",
  "Will it rain this week?",
  "How did weather affect yield?",
];
const TOOL_LABELS = {
  get_field_overview: "Field overview",
  get_crop_health: "Crop health",
  get_problem_zones: "Productivity zones",
  get_season_weather: "Season weather",
  get_weather_forecast: "Forecast",
  get_soil: "Soil survey",
  get_yield_estimate: "Yield estimate",
};

export default function AskPanel({ fieldId }) {
  const [history, setHistory] = useState([]);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [left, setLeft] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const limitHit = left === 0;

  async function ask(text) {
    const q = text.trim();
    if (!q || loading || limitHit) return;
    setError("");
    setLoading(true);
    setQuestion("");
    try {
      const r = await askQuestion({
        field_id: fieldId,
        question: q,
        session_id: sessionId,
      });
      const sources =
        [...new Set(r.tools_used)].map((t) => TOOL_LABELS[t] || t).join(", ") ||
        "None";
      setSessionId(r.session_id);
      setLeft(r.questions_left);
      setHistory((h) => [
        ...h,
        { role: "user", text: q },
        {
          role: "assistant",
          text: r.answer,
          meta: `Sources: ${sources} · ${r.verified ? "Verified" : "Needs review"}`,
        },
      ]);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="scroll" style={{ height: 380 }} aria-live="polite">
        {history.length === 0 && (
          <p className="caption" style={{ margin: 0 }}>
            Ask a question about this field. Answers come from the field's data,
            and every number is checked.
          </p>
        )}
        {history.map((m, i) => (
          <div key={i} className={`msg ${m.role === "user" ? "msg-user" : ""}`}>
            <ReactMarkdown>{m.text}</ReactMarkdown>
            {m.meta && <p className="caption">{m.meta}</p>}
          </div>
        ))}
        {loading && <p className="caption">Checking the field data...</p>}
      </div>

      <div className="examples">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            className="example"
            onClick={() => ask(q)}
            disabled={loading || limitHit}
          >
            {q}
          </button>
        ))}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {limitHit ? (
        <p className="caption">
          You have reached the question limit for this demo session.
        </p>
      ) : (
        <form
          className="ask-row"
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
        >
          <label htmlFor="ask" style={{ position: "absolute", left: -9999 }}>
            Ask a question about this field
          </label>
          <input
            id="ask"
            className="input"
            value={question}
            maxLength={500}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about this field"
          />
          <button
            type="submit"
            className="btn"
            disabled={loading || !question.trim()}
          >
            Ask
          </button>
        </form>
      )}
    </div>
  );
}

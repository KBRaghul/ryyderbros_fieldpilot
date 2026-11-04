import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { askQuestion } from "../api";
import Checked, { NeedsReview } from "./Checked";

const STARTERS = [
  "Why is part of this field weak?",
  "Will it rain this week?",
  "How did weather affect yield?",
];
// Follow-ups that fit the data the last answer used
const FOLLOW_UPS = {
  get_problem_zones: ["Which soil should I test first?", "How large is the weak zone?"],
  get_soil: ["Should I lime this field?", "Which soil holds the least water?"],
  get_season_weather: ["How long was the longest dry spell?", "Which month was driest?"],
  get_yield_estimate: ["What lowered the yield estimate most?", "How does it compare with USDA?"],
  get_weather_forecast: ["Is this week good for field work?"],
  get_crop_health: ["When did the crop peak?"],
};
const TOOL_LABELS = {
  get_field_overview: "Field overview",
  get_crop_health: "Crop health",
  get_problem_zones: "Productivity zones",
  get_season_weather: "Season weather",
  get_weather_forecast: "Forecast",
  get_soil: "Soil survey",
  get_yield_estimate: "Yield estimate",
};
const MAX_QUESTION = 500; // the API limit
const MAX_QUOTE = 160;

function suggestionsFor(history) {
  const last = [...history].reverse().find((m) => m.role === "assistant");
  if (!last) return STARTERS;
  const asked = new Set(history.filter((m) => m.role === "user").map((m) => m.text));
  const next = last.tools.flatMap((t) => FOLLOW_UPS[t] || []).filter((q) => !asked.has(q));
  return [...new Set(next)].slice(0, 3);
}

// The question sent to the API: the quoted words first, trimmed to fit the limit
function withQuote(question, quote) {
  if (!quote) return question;
  const room = MAX_QUESTION - question.length - 12;
  const q = quote.length > Math.min(room, MAX_QUOTE) ? quote.slice(0, Math.max(0, Math.min(room, MAX_QUOTE) - 1)) + "…" : quote;
  return `About "${q}": ${question}`;
}

export default function AskPanel({ fieldId }) {
  const [history, setHistory] = useState([]);
  const [question, setQuestion] = useState("");
  const [quote, setQuote] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [left, setLeft] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pill, setPill] = useState(null); // { top, left, text } over a selection
  const threadRef = useRef(null);
  const inputRef = useRef(null);
  const limitHit = left === 0;
  const suggestions = suggestionsFor(history);
  const showMenu = menuOpen && !question.trim() && suggestions.length > 0 && !loading && !limitHit;

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, loading]);

  async function ask(text) {
    const q = text.trim();
    if (!q || loading || limitHit) return;
    const sent = withQuote(q, quote);
    setError("");
    setLoading(true);
    setQuestion("");
    setMenuOpen(false);
    setActive(-1);
    setHistory((h) => [...h, { role: "user", text: q, quote }]);
    setQuote("");
    try {
      const r = await askQuestion({ field_id: fieldId, question: sent, session_id: sessionId });
      const tools = [...new Set(r.tools_used)];
      setSessionId(r.session_id);
      setLeft(r.questions_left);
      setHistory((h) => [
        ...h,
        {
          role: "assistant",
          text: r.answer,
          tools,
          sources: tools.map((t) => TOOL_LABELS[t] || t).join(", ") || "None",
          verified: r.verified,
        },
      ]);
      setMenuOpen(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  // Selecting words in an answer shows a Reply pill above them
  function onSelect() {
    const sel = window.getSelection();
    const text = sel?.toString().replace(/\s+/g, " ").trim();
    const thread = threadRef.current;
    if (!text || !sel.rangeCount || !thread) return setPill(null);
    const range = sel.getRangeAt(0);
    const answer = range.commonAncestorContainer.parentElement?.closest(".turn-answer");
    if (!answer || !thread.contains(answer)) return setPill(null);
    const r = range.getBoundingClientRect();
    const box = thread.getBoundingClientRect();
    setPill({
      text,
      top: r.top - box.top + thread.scrollTop - 40,
      left: Math.min(Math.max(r.left - box.left + r.width / 2, 48), box.width - 48),
    });
  }

  function reply() {
    setQuote(pill.text);
    setPill(null);
    window.getSelection()?.removeAllRanges();
    inputRef.current?.focus();
  }

  function onKeyDown(e) {
    if (showMenu && e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % suggestions.length);
    } else if (showMenu && e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Escape") {
      if (showMenu) setMenuOpen(false);
      else if (quote) setQuote("");
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (showMenu && active >= 0) ask(suggestions[active]);
      else ask(question);
    }
  }

  return (
    <div className="chat">
      <div
        className="thread"
        ref={threadRef}
        aria-live="polite"
        onMouseUp={onSelect}
        onScroll={() => pill && setPill(null)}
      >
        {history.length === 0 && !loading && (
          <p className="empty">
            Ask a question about this field. Answers come from the field's data,
            and every number is checked. Select words in an answer to reply to them.
          </p>
        )}
        {history.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="turn-user">
              {m.quote && <p className="turn-quote">{m.quote}</p>}
              <p className="bubble">{m.text}</p>
            </div>
          ) : (
            <div key={i} className="turn-answer">
              <ReactMarkdown>{m.text}</ReactMarkdown>
              <div className="msg-meta">
                {m.verified ? <Checked /> : <NeedsReview />}
                <span>Sources: {m.sources}</span>
              </div>
            </div>
          ),
        )}
        {loading && (
          <p className="thinking" role="status">
            <span className="spinner" aria-hidden="true" />
            <span className="shimmer">Checking the field data…</span>
          </p>
        )}
        {pill && (
          <button
            type="button"
            className="reply-pill"
            style={{ top: pill.top, left: pill.left }}
            onMouseDown={(e) => e.preventDefault()}
            onClick={reply}
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 9.5c0-2.8 1.3-4.6 3.6-5.5l.5 1C5.8 5.6 5.1 6.6 5 8h2v4H3V9.5Zm6 0c0-2.8 1.3-4.6 3.6-5.5l.5 1c-1.3.6-2 1.6-2.1 3H13v4H9V9.5Z" />
            </svg>
            Reply
          </button>
        )}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {limitHit ? (
        <p className="caption">You have reached the question limit for this demo session.</p>
      ) : (
        <div className="composer-wrap">
          {showMenu && (
            <div className="suggest" id="ask-suggestions">
              <div className="suggest-keys" aria-hidden="true">
                <span><kbd>▲</kbd><kbd>▼</kbd> to navigate</span>
                <span><kbd>↩</kbd> to select</span>
                <span className="suggest-esc"><kbd>esc</kbd> to close</span>
              </div>
              <ul role="listbox" aria-label="Suggested questions">
                {suggestions.map((s, i) => (
                  <li
                    key={s}
                    id={`ask-suggestion-${i}`}
                    role="option"
                    aria-selected={i === active}
                    className={i === active ? "is-active" : undefined}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => ask(s)}
                  >
                    <span aria-hidden="true">→</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
          >
            {quote && (
              <div className="quote-chip">
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M6 4 2.5 7.5 6 11M3 7.5h6.5a4 4 0 0 1 4 4V12" />
                </svg>
                <span>{quote}</span>
                <button type="button" aria-label="Remove quote" onClick={() => setQuote("")}>
                  ×
                </button>
              </div>
            )}
            <label htmlFor="ask" className="visually-hidden">
              Ask a question about this field
            </label>
            <textarea
              id="ask"
              ref={inputRef}
              rows={1}
              value={question}
              maxLength={MAX_QUESTION}
              placeholder={quote ? "Ask about the quoted words" : "Ask about this field"}
              onChange={(e) => setQuestion(e.target.value)}
              onFocus={() => setMenuOpen(true)}
              onBlur={() => setMenuOpen(false)}
              onKeyDown={onKeyDown}
              aria-controls={showMenu ? "ask-suggestions" : undefined}
              aria-activedescendant={showMenu && active >= 0 ? `ask-suggestion-${active}` : undefined}
            />
            <div className="composer-row">
              <span className="num caption">
                {left != null ? `${left} questions left` : "Answers are number-checked"}
              </span>
              <button
                type="submit"
                className="send"
                aria-label="Send question"
                disabled={loading || !question.trim()}
              >
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" />
                </svg>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

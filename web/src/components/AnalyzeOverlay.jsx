import { createPortal } from "react-dom";

// Full-page blur with a progress card while a drawn field is analyzed.
export default function AnalyzeOverlay({ percent, seconds }) {
  return createPortal(
    <div className="overlay">
      <div
        className="overlay-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="analyze-title"
      >
        <div className="overlay-head">
          <h2 id="analyze-title">Analyzing your field</h2>
          <span className="num overlay-percent" aria-hidden="true">
            {percent}%
          </span>
        </div>
        <div
          className="progress"
          role="progressbar"
          aria-label="Estimated progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <div className="progress-fill" style={{ transform: `scaleX(${percent / 100})` }} />
        </div>
        <p className="overlay-meta">
          <span>Reading satellite images, weather, soil, and the yield model</span>
          <span className="num">{seconds}s</span>
        </p>
        <p className="caption">
          This usually takes 1 to 2 minutes. Your field opens when it is ready.
        </p>
      </div>
    </div>,
    document.body,
  );
}

// The number-checked mark: shown wherever every number was checked against the field data.
export default function Checked({ children = "Number-checked" }) {
  return (
    <span className="checked">
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="m3.5 8.5 3 3 6-7" />
      </svg>
      {children}
    </span>
  );
}

export function NeedsReview({ children = "Needs review" }) {
  return <span className="review">{children}</span>;
}

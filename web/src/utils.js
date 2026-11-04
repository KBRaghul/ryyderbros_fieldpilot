const DATE_FMT = new Intl.DateTimeFormat("en-US", {
  month: "long",
  day: "numeric",
});

export const formatDate = (iso) => DATE_FMT.format(new Date(`${iso}T12:00:00`));
export const signed = (n, digits = 1) =>
  (n < 0 ? "\u2212" : "") + Math.abs(n).toFixed(digits);
export const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
export const where = (direction) =>
  direction === "center or scattered"
    ? "scattered across the field"
    : `in the ${direction}`;

// Estimated progress: the server only reports processing or ready, so the bar follows the
// time a real analysis takes (a typical 90 s run reaches about 77%), and shows 100% only when the field is ready.
const TIME_CONSTANT_S = 55;
const CAP = 95;

export function estimatedPercent(seconds) {
  return Math.min(CAP, Math.floor(CAP * (1 - Math.exp(-seconds / TIME_CONSTANT_S))));
}

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

import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDate } from "../utils";

const ACCENT = "#1f6f43";
const SECOND = "#9a9c96";
const AXIS = {
  fontSize: 11,
  fill: "#6b6d67",
  fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
};
const MONTH = new Intl.DateTimeFormat("en-US", { month: "short" });
const monthTick = (iso) => MONTH.format(new Date(`${iso}T12:00:00`));

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tip">
      <p>{formatDate(label)}</p>
      <p>
        NDVI <span className="num">{row.ndvi?.toFixed(2)}</span>
      </p>
      {row.ndre != null && (
        <p>
          NDRE <span className="num">{row.ndre.toFixed(2)}</span>
        </p>
      )}
    </div>
  );
}

export default function NdviChart({ ndvi }) {
  const series = ndvi?.series || [];
  const peak = ndvi?.peak;
  if (!series.length)
    return <p className="empty">No satellite series available.</p>;
  const data = series.map((r) => ({
    ...r,
    peak: peak && r.date === peak.date ? r.ndvi : null,
  }));
  // One tick per month, on the first image date of that month
  const ticks = data
    .filter((r, i) => i === 0 || r.date.slice(0, 7) !== data[i - 1].date.slice(0, 7))
    .map((r) => r.date);

  return (
    <>
      <ul className="chart-legend" aria-label="Chart key">
        <li>
          <span className="key-line" />
          NDVI
        </li>
        <li>
          <span className="key-line dashed" />
          NDRE
        </li>
        {peak && (
          <li>
            <span className="key-dot" />
            In-season peak
          </li>
        )}
      </ul>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart
          data={data}
          margin={{ top: 16, right: 4, left: -24, bottom: 0 }}
        >
          <CartesianGrid stroke="rgba(27,28,26,0.08)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={AXIS}
            ticks={ticks}
            tickFormatter={monthTick}
            tickLine={false}
            axisLine={{ stroke: "rgba(27,28,26,0.18)" }}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tick={AXIS}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            content={<Tip />}
            cursor={{ stroke: "rgba(27,28,26,0.18)" }}
          />
          <Line
            type="monotone"
            dataKey="ndre"
            name="NDRE"
            stroke={SECOND}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            dot={false}
            activeDot={{ r: 3, fill: SECOND, stroke: "#fff" }}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="ndvi"
            name="NDVI"
            stroke={ACCENT}
            strokeWidth={2}
            dot={{ r: 2, fill: ACCENT, stroke: "none" }}
            activeDot={{ r: 4, fill: ACCENT, stroke: "#fff", strokeWidth: 2 }}
            isAnimationActive={false}
          />
          <Scatter
            dataKey="peak"
            name="In-season peak"
            fill="#1b1c1a"
            shape="diamond"
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </>
  );
}

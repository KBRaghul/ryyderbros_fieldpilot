import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  ComposedChart,
} from "recharts";

const AXIS = { fontSize: 12, fill: "#1A202C" };

export default function NdviChart({ ndvi }) {
  const series = ndvi?.series || [];
  const peak = ndvi?.peak;
  if (!series.length)
    return <p className="caption">No satellite series available.</p>;
  const data = series.map((r) => ({
    ...r,
    peak: peak && r.date === peak.date ? r.ndvi : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart
        data={data}
        margin={{ top: 10, right: 10, left: -10, bottom: 0 }}
      >
        <CartesianGrid stroke="#E5E7EB" />
        <XAxis
          dataKey="date"
          tick={AXIS}
          minTickGap={40}
          label={{
            value: "Date",
            position: "insideBottom",
            offset: -2,
            fontSize: 12,
          }}
        />
        <YAxis
          domain={[0, 1]}
          tick={AXIS}
          label={{
            value: "Index value",
            angle: -90,
            position: "insideLeft",
            offset: 20,
            fontSize: 12,
          }}
        />
        <Tooltip />
        <Legend
          verticalAlign="bottom"
          wrapperStyle={{ fontSize: 13, paddingTop: 10 }}
        />
        <Line
          type="monotone"
          dataKey="ndvi"
          name="NDVI"
          stroke="#0072B2"
          strokeWidth={2.5}
          dot={{ r: 3 }}
        />
        <Line
          type="monotone"
          dataKey="ndre"
          name="NDRE"
          stroke="#E69F00"
          strokeWidth={2.5}
          strokeDasharray="6 4"
          dot={{ r: 3, shape: "square" }}
        />
        <Scatter
          dataKey="peak"
          name="In-season peak"
          fill="#1A202C"
          shape="diamond"
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export default function DataTab({ ctx }) {
  const monthly = ctx.weather?.monthly || [];
  const soils = ctx.soil?.units || [];
  return (
    <div style={{ maxHeight: 560, overflowY: "auto" }}>
      {monthly.length > 0 && (
        <>
          <h3 className="section-title">Weather by month</h3>
          <table>
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col" className="num">Rain (in)</th>
                <th scope="col" className="num">Crop water demand (in)</th>
                <th scope="col" className="num">Water balance (in)</th>
                <th scope="col" className="num">Average high (°F)</th>
              </tr>
            </thead>
            <tbody>
              {monthly.map((m) => (
                <tr key={m.month}>
                  <td>{m.month}</td>
                  <td className="num">{m.rain_in}</td>
                  <td className="num">{m.et0_in}</td>
                  <td className="num">{m.balance_in}</td>
                  <td className="num">{m.avg_tmax_f}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {soils.length > 0 && (
        <>
          <h3 className="section-title">Soil types</h3>
          <table>
            <thead>
              <tr>
                <th scope="col">Soil</th>
                <th scope="col" className="num">Share of field (%)</th>
                <th scope="col" className="num">Available water (in)</th>
                <th scope="col">Drainage</th>
                <th scope="col" className="num">pH</th>
                <th scope="col">Capability class</th>
              </tr>
            </thead>
            <tbody>
              {soils.map((u) => (
                <tr key={u.mukey}>
                  <td>{u.name}</td>
                  <td className="num">{u.percent}</td>
                  <td className="num">{u.available_water_in}</td>
                  <td>{u.drainage}</td>
                  <td className="num">{u.ph}</td>
                  <td>{u.capability_class}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

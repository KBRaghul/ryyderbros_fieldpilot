export default function DataTab({ ctx }) {
  const monthly = ctx.weather?.monthly || [];
  const soils = ctx.soil?.units || [];
  return (
    <div className="scroll" style={{ height: 560, marginTop: 0 }}>
      {monthly.length > 0 && (
        <>
          <h3 className="panel-title">Weather by month</h3>
          <table>
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col">Rain (in)</th>
                <th scope="col">Crop water demand (in)</th>
                <th scope="col">Water balance (in)</th>
                <th scope="col">Average high (°F)</th>
              </tr>
            </thead>
            <tbody>
              {monthly.map((m) => (
                <tr key={m.month}>
                  <td>{m.month}</td>
                  <td>{m.rain_in}</td>
                  <td>{m.et0_in}</td>
                  <td>{m.balance_in}</td>
                  <td>{m.avg_tmax_f}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {soils.length > 0 && (
        <>
          <h3 className="panel-title" style={{ marginTop: 20 }}>
            Soil types
          </h3>
          <table>
            <thead>
              <tr>
                <th scope="col">Soil</th>
                <th scope="col">Share of field (%)</th>
                <th scope="col">Available water (in)</th>
                <th scope="col">Drainage</th>
                <th scope="col">pH</th>
                <th scope="col">Capability class</th>
              </tr>
            </thead>
            <tbody>
              {soils.map((u) => (
                <tr key={u.mukey}>
                  <td>{u.name}</td>
                  <td>{u.percent}</td>
                  <td>{u.available_water_in}</td>
                  <td>{u.drainage}</td>
                  <td>{u.ph}</td>
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

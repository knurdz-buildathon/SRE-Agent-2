import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-card border border-border rounded p-2 text-xs">
      <p className="text-white font-medium">{label}</p>
      <p className="text-muted">Uptime: {d.uptime_percent}%</p>
      <p className="text-muted">Checks: {d.total_checks}</p>
      <p className="text-muted">OK: {d.successful_checks}</p>
    </div>
  );
};

export default function UptimeChart({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-muted text-sm text-center py-8">No uptime data available</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
        <XAxis
          dataKey="date"
          tick={{ fill: '#9ca3af', fontSize: 10 }}
          tickFormatter={(v) => v.slice(5)}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: '#9ca3af', fontSize: 10 }}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="uptime_percent" radius={[2, 2, 0, 0]}>
          {data.map((entry, idx) => (
            <Cell
              key={idx}
              fill={
                entry.uptime_percent >= 99
                  ? '#22c55e'
                  : entry.uptime_percent >= 95
                  ? '#f59e0b'
                  : '#ef4444'
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

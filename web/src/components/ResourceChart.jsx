import React from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card border border-border rounded p-2 text-xs">
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}
        </p>
      ))}
    </div>
  );
};

export default function ResourceChart({ data, dataKey, name, color, unit = '', maxY }) {
  if (!data || data.length === 0) {
    return <p className="text-muted text-sm text-center py-8">No data available</p>;
  }

  const sorted = [...data].sort((a, b) =>
    (a.collected_at || '').localeCompare(b.collected_at || '')
  );

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={sorted} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
        <defs>
          <linearGradient id={`grad-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="collected_at"
          tick={{ fill: '#9ca3af', fontSize: 9 }}
          tickFormatter={(v) => v ? v.slice(11, 16) : ''}
        />
        <YAxis
          domain={maxY ? [0, maxY] : undefined}
          tick={{ fill: '#9ca3af', fontSize: 9 }}
          tickFormatter={(v) => `${v.toFixed(0)}${unit}`}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey={dataKey}
          name={name}
          stroke={color}
          fill={`url(#grad-${dataKey})`}
          strokeWidth={1.5}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

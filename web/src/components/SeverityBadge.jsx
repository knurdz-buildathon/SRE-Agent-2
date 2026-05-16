import React from 'react';

export default function SeverityBadge({ severity }) {
  const config = {
    critical: 'bg-unhealthy/15 text-unhealthy border-unhealthy/30',
    warning: 'bg-warn/15 text-warn border-warn/30',
    degraded: 'bg-degraded/15 text-degraded border-degraded/30',
  };

  const cls = config[severity] || 'bg-gray-600/20 text-muted border-gray-600/30';

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}>
      {severity || 'info'}
    </span>
  );
}

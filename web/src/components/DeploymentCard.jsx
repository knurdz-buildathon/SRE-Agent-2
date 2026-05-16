import React from 'react';
import { useNavigate } from 'react-router-dom';
import StatusBadge from './StatusBadge';

export default function DeploymentCard({ deployment }) {
  const navigate = useNavigate();
  const { id, slug, environment, status, uptime_percent, last_error, open_incidents } = deployment;

  const statusColor =
    status === 'up' || status === 'healthy'
      ? 'border-l-healthy'
      : 'border-l-unhealthy';

  return (
    <div
      onClick={() => navigate(`/deployment/${id}`)}
      className={`bg-card border border-border border-l-4 ${statusColor} rounded-lg p-4 cursor-pointer hover:bg-white/[0.03] transition-colors`}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">{slug}</h3>
        <StatusBadge status={status} />
      </div>
      <div className="flex items-center gap-3 text-xs text-muted">
        <span>{environment}</span>
        {uptime_percent !== null && uptime_percent !== undefined && (
          <span>Uptime: {uptime_percent}%</span>
        )}
        {open_incidents > 0 && (
          <span className="text-unhealthy">{open_incidents} incident{open_incidents > 1 ? 's' : ''}</span>
        )}
      </div>
      {last_error && (
        <p className="text-xs text-unhealthy/80 mt-2 truncate">{last_error}</p>
      )}
    </div>
  );
}

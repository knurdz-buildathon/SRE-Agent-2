import React from 'react';
import { useNavigate } from 'react-router-dom';
import StatusBadge from './StatusBadge';

export default function DeploymentCard({ deployment }) {
  const navigate = useNavigate();
  const {
    id,
    slug,
    environment,
    status,
    site_status,
    container_status,
    container_name,
    uptime_percent,
    last_error,
    open_incidents,
  } = deployment;

  const displayStatus = container_status || status;
  const siteStatus = site_status || status;

  const displayKey = typeof displayStatus === 'string' ? displayStatus.toLowerCase() : '';
  const statusColor =
    displayKey === 'up' || displayKey === 'healthy' || displayKey === 'running'
      ? 'border-l-healthy'
      : displayKey === 'down' || displayKey === 'unhealthy' || displayKey === 'stopped' || displayKey === 'restarting'
        ? 'border-l-unhealthy'
        : 'border-l-gray-600';

  return (
    <div
      onClick={() => navigate(`/deployment/${id}`)}
      className={`bg-card border border-border border-l-4 ${statusColor} rounded-lg p-4 cursor-pointer hover:bg-white/[0.03] transition-colors`}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">{slug}</h3>
        <StatusBadge status={displayStatus} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
        <span>{environment}</span>
        {container_name && <span className="truncate max-w-[12rem]">{container_name}</span>}
        {uptime_percent !== null && uptime_percent !== undefined && (
          <span>Uptime: {uptime_percent}%</span>
        )}
        {open_incidents > 0 && (
          <span className="text-unhealthy">{open_incidents} incident{open_incidents > 1 ? 's' : ''}</span>
        )}
      </div>
      <div className="flex items-center gap-2 mt-3 text-xs text-muted">
        <span>Website</span>
        <StatusBadge status={siteStatus} />
      </div>
      {last_error && (
        <p className="text-xs text-unhealthy/80 mt-2 truncate">Website check: {last_error}</p>
      )}
    </div>
  );
}

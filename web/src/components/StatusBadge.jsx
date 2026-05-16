import React from 'react';

export default function StatusBadge({ status }) {
  const config = {
    healthy: 'bg-healthy/15 text-healthy border-healthy/30',
    unhealthy: 'bg-unhealthy/15 text-unhealthy border-unhealthy/30',
    warning: 'bg-warn/15 text-warn border-warn/30',
    degraded: 'bg-degraded/15 text-degraded border-degraded/30',
    critical: 'bg-unhealthy/15 text-unhealthy border-unhealthy/30',
    open: 'bg-unhealthy/15 text-unhealthy border-unhealthy/30',
    resolved: 'bg-healthy/15 text-healthy border-healthy/30',
    running: 'bg-healthy/15 text-healthy border-healthy/30',
    restarting: 'bg-unhealthy/15 text-unhealthy border-unhealthy/30',
    stopped: 'bg-unhealthy/15 text-unhealthy border-unhealthy/30',
    unknown: 'bg-gray-600/20 text-muted border-gray-600/30',
  };

  const cls = config[status] || config.unknown;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}>
      {status || 'unknown'}
    </span>
  );
}

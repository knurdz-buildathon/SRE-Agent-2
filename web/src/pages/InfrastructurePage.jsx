import React, { useEffect, useState } from 'react';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import MetricCard from '../components/MetricCard';
import ResourceChart from '../components/ResourceChart';

export default function InfrastructurePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const result = await api.getInfrastructure();
      setData(result);
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="p-6 text-muted">Loading infrastructure...</div>;
  if (!data) return <div className="p-6 text-unhealthy">Failed to load infrastructure data</div>;

  const latestVPS = data.vps_targets?.[0] || {};
  const latestSizes = data.docker_sizes?.[0] || {};

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Infrastructure</h1>
        <p className="text-sm text-muted">VPS, Docker, and resource overview</p>
      </div>

      {/* VPS Info */}
      <div className="bg-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">VPS Target</h2>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-muted text-xs">OS</p>
            <p className="text-white">{latestVPS.os_name || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Kernel</p>
            <p className="text-white text-xs">{latestVPS.kernel || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Docker</p>
            <p className="text-white">{latestVPS.docker_version || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">CPUs</p>
            <p className="text-white">{latestVPS.cpu_count || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Memory</p>
            <p className="text-white">{latestVPS.memory_total_mb ? `${latestVPS.memory_total_mb} MB` : '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Disk</p>
            <p className="text-white">
              {latestVPS.disk_used_gb && latestVPS.disk_total_gb
                ? `${latestVPS.disk_used_gb} / ${latestVPS.disk_total_gb} GB`
                : '-'}
            </p>
          </div>
        </div>
      </div>

      {/* Docker sizes */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard title="Images" value={`${latestSizes.images_mb || 0} MB`} color="text-accent" />
        <MetricCard title="Containers" value={`${latestSizes.containers_mb || 0} MB`} color="text-accent" />
        <MetricCard title="Volumes" value={`${latestSizes.volumes_mb || 0} MB`} color="text-accent" />
        <MetricCard title="Build Cache" value={`${latestSizes.build_cache_mb || 0} MB`} color="text-accent" />
      </div>

      {/* Resource charts */}
      {data.latest_metrics && data.latest_metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-card border border-border rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-3">CPU Usage by Deployment</h3>
            <div className="space-y-3">
              {data.latest_metrics.map((m) => (
                <div key={m.deployment_id} className="flex items-center gap-3">
                  <span className="text-xs text-muted w-28 truncate">{m.slug || m.deployment_id}</span>
                  <div className="flex-1 bg-border rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${m.cpu_percent > 90 ? 'bg-unhealthy' : m.cpu_percent > 70 ? 'bg-warn' : 'bg-healthy'}`}
                      style={{ width: `${Math.min(m.cpu_percent || 0, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-muted w-14 text-right">{(m.cpu_percent || 0).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
          <div className="bg-card border border-border rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-3">Memory Usage by Deployment</h3>
            <div className="space-y-3">
              {data.latest_metrics.map((m) => {
                const pct = m.memory_limit_mb ? (m.memory_usage_mb / m.memory_limit_mb) * 100 : 0;
                return (
                  <div key={m.deployment_id} className="flex items-center gap-3">
                    <span className="text-xs text-muted w-28 truncate">{m.slug || m.deployment_id}</span>
                    <div className="flex-1 bg-border rounded-full h-2">
                      <div
                        className={`h-2 rounded-full ${pct > 90 ? 'bg-unhealthy' : pct > 70 ? 'bg-warn' : 'bg-healthy'}`}
                        style={{ width: `${Math.min(pct, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted w-20 text-right">
                      {m.memory_usage_mb?.toFixed(0) || 0} / {m.memory_limit_mb?.toFixed(0) || 0} MB
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Container list */}
      <div className="bg-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Containers</h2>
        {data.containers && data.containers.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="pb-2 pr-4">Name</th>
                  <th className="pb-2 pr-4">Image</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.containers.map((c, idx) => (
                  <tr key={c.name || idx} className="border-b border-border/50">
                    <td className="py-2 pr-4 text-xs font-mono">{c.name}</td>
                    <td className="py-2 pr-4 text-xs">{c.image}</td>
                    <td className="py-2">
                      <StatusBadge status={c.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted text-sm">No containers found</p>
        )}
      </div>
    </div>
  );
}

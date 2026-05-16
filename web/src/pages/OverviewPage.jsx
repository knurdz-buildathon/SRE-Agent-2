import React, { useEffect, useState } from 'react';
import { api } from '../api';
import MetricCard from '../components/MetricCard';
import DeploymentCard from '../components/DeploymentCard';

export default function OverviewPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const result = await api.getOverview();
      setData(result);
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted">Loading overview...</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-unhealthy">Failed to load overview data</div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Overview</h1>
        <p className="text-sm text-muted">Website availability at a glance</p>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard
          title="Total Deployments"
          value={data.total_deployments}
          color="text-white"
        />
        <MetricCard
          title="Up"
          value={data.up_count}
          color="text-healthy"
        />
        <MetricCard
          title="Down"
          value={data.down_count}
          color="text-unhealthy"
        />
        <MetricCard
          title="Open Incidents"
          value={data.open_incidents}
          color={data.open_incidents > 0 ? 'text-warn' : 'text-healthy'}
        />
      </div>

      {/* Deployment cards */}
      <div>
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Deployments</h2>
        {data.deployments.length === 0 ? (
          <p className="text-muted text-sm">No deployments found. Published Docker ports are auto-discovered; optionally add sre.monitor labels for custom URLs.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.deployments.map((dep) => (
              <DeploymentCard key={dep.id} deployment={dep} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

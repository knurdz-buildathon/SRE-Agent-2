import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import UptimeChart from '../components/UptimeChart';
import ResourceChart from '../components/ResourceChart';

const TABS = ['Health Checks', 'Errors', 'Resource Usage', 'Uptime', 'Env Issues', 'User Errors'];

export default function DeploymentPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState(0);
  const [dep, setDep] = useState(null);
  const [healthData, setHealthData] = useState([]);
  const [errors, setErrors] = useState([]);
  const [stats, setStats] = useState([]);
  const [uptime, setUptime] = useState([]);
  const [envIssues, setEnvIssues] = useState([]);
  const [userErrors, setUserErrors] = useState([]);

  useEffect(() => {
    async function load() {
      const overview = await api.getOverview();
      const found = overview?.deployments?.find((d) => d.id === id);
      setDep(found || null);

      const [h, e, s, u, ev, ue] = await Promise.all([
        api.getDeploymentHealth(id),
        api.getDeploymentErrors(id),
        api.getDeploymentStats(id, 24),
        api.getDeploymentUptime(id, 30),
        api.getDeploymentEnvIssues(id),
        api.getDeploymentUserErrors(id),
      ]);
      setHealthData(h || []);
      setErrors(e || []);
      setStats(s || []);
      setUptime(u || []);
      setEnvIssues(ev || []);
      setUserErrors(ue || []);
    }
    load();
  }, [id]);

  if (!dep) {
    return <div className="p-6 text-muted">Loading deployment...</div>;
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/')}
            className="text-muted hover:text-white text-sm mb-2 flex items-center gap-1"
          >
            ← Back
          </button>
          <h1 className="text-xl font-bold text-white">{dep.slug}</h1>
          <div className="flex items-center gap-3 mt-1">
            <StatusBadge status={dep.status} />
            <span className="text-xs text-muted">{dep.environment}</span>
            {dep.uptime_percent !== null && dep.uptime_percent !== undefined && (
              <span className="text-xs text-muted">Uptime: {dep.uptime_percent}%</span>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {TABS.map((tab, idx) => (
          <button
            key={tab}
            onClick={() => setActiveTab(idx)}
            className={`px-3 py-2 text-sm transition-colors ${
              activeTab === idx
                ? 'text-accent border-b-2 border-accent'
                : 'text-muted hover:text-gray-300'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === 0 && <HealthTab data={healthData} />}
        {activeTab === 1 && <ErrorsTab data={errors} />}
        {activeTab === 2 && <ResourceTab data={stats} />}
        {activeTab === 3 && <UptimeTab data={uptime} />}
        {activeTab === 4 && <EnvIssuesTab data={envIssues} />}
        {activeTab === 5 && <UserErrorsTab data={userErrors} />}
      </div>
    </div>
  );
}

function HealthTab({ data }) {
  if (!data.length) return <p className="text-muted text-sm">No health checks yet</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-muted border-b border-border">
            <th className="pb-2 pr-4">Time</th>
            <th className="pb-2 pr-4">Type</th>
            <th className="pb-2 pr-4">Status</th>
            <th className="pb-2 pr-4">Response Time</th>
            <th className="pb-2">Error</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.id} className="border-b border-border/50">
              <td className="py-2 pr-4 text-muted text-xs">
                {row.checked_at ? row.checked_at.slice(11, 19) : '-'}
              </td>
              <td className="py-2 pr-4">{row.check_type}</td>
              <td className="py-2 pr-4">
                <StatusBadge status={row.success ? 'up' : 'down'} />
              </td>
              <td className="py-2 pr-4">
                {row.response_time_ms !== null ? `${row.response_time_ms}ms` : '-'}
              </td>
              <td className="py-2 text-xs text-unhealthy/80 max-w-xs truncate">
                {row.error_message || '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorsTab({ data }) {
  if (!data.length) return <p className="text-healthy text-sm">No errors found</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-muted border-b border-border">
            <th className="pb-2 pr-4">Time</th>
            <th className="pb-2 pr-4">Type</th>
            <th className="pb-2 pr-4">Status Code</th>
            <th className="pb-2">Error</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.id} className="border-b border-border/50">
              <td className="py-2 pr-4 text-muted text-xs">
                {row.checked_at ? row.checked_at.slice(11, 19) : '-'}
              </td>
              <td className="py-2 pr-4">{row.check_type}</td>
              <td className="py-2 pr-4 text-unhealthy">{row.status_code || '-'}</td>
              <td className="py-2 text-xs text-unhealthy/80 max-w-md truncate">
                {row.error_message || '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResourceTab({ data }) {
  if (!data.length) return <p className="text-muted text-sm">No resource data yet</p>;
  return (
    <div className="grid grid-cols-2 gap-6">
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-300 mb-3">CPU Usage</h3>
        <ResourceChart data={data} dataKey="cpu_percent" name="CPU %" color="#3b82f6" unit="%" maxY={100} />
      </div>
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-300 mb-3">Memory Usage</h3>
        <ResourceChart data={data} dataKey="memory_usage_mb" name="Memory MB" color="#f59e0b" unit="MB" />
      </div>
    </div>
  );
}

function UptimeTab({ data }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-300 mb-3">Uptime History (30 days)</h3>
      <UptimeChart data={data} />
    </div>
  );
}

function EnvIssuesTab({ data }) {
  if (!data.length) return <p className="text-healthy text-sm">No environment issues detected</p>;
  return (
    <div className="space-y-3">
      {data.map((issue) => (
        <div key={issue.id} className="bg-card border border-border rounded-lg p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-white">{issue.title}</h3>
            <StatusBadge status={issue.status} />
          </div>
          <p className="text-xs text-muted mt-1">
            {issue.error_category} · {issue.severity} · {issue.started_at?.slice(0, 16)}
          </p>
          {issue.suggested_fix && (
            <p className="text-xs text-accent mt-2 bg-accent/10 rounded p-2">
              Fix: {issue.suggested_fix}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function UserErrorsTab({ data }) {
  if (!data.length) return <p className="text-muted text-sm">No user errors tracked</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-muted border-b border-border">
            <th className="pb-2 pr-4">Path</th>
            <th className="pb-2 pr-4">Method</th>
            <th className="pb-2 pr-4">Status</th>
            <th className="pb-2 pr-4">Category</th>
            <th className="pb-2 pr-4">Count</th>
            <th className="pb-2">Last Seen</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row, idx) => (
            <tr key={row.id || idx} className="border-b border-border/50">
              <td className="py-2 pr-4 text-xs font-mono">{row.path}</td>
              <td className="py-2 pr-4 text-xs">{row.method}</td>
              <td className="py-2 pr-4 text-unhealthy text-xs">{row.status_code}</td>
              <td className="py-2 pr-4 text-xs">{row.error_category}</td>
              <td className="py-2 pr-4 text-xs">{row.count}</td>
              <td className="py-2 text-xs text-muted">
                {row.last_seen ? row.last_seen.slice(11, 16) : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

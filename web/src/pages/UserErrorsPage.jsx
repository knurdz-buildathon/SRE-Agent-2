import React, { useEffect, useState } from 'react';
import { api } from '../api';
import MetricCard from '../components/MetricCard';

export default function UserErrorsPage() {
  const [summary, setSummary] = useState(null);
  const [errors, setErrors] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const [s, e] = await Promise.all([
        api.getUserErrorsSummary(),
        api.getUserErrors(),
      ]);
      setSummary(s || null);
      setErrors(e || []);
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="p-6 text-muted">Loading user errors...</div>;

  const totalErrors = errors.reduce((sum, e) => sum + (e.count || 0), 0);
  const distinctErrors = errors.length;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">User Errors</h1>
        <p className="text-sm text-muted">Client-facing errors detected from Traefik logs</p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard title="Total Error Hits" value={totalErrors} color="text-unhealthy" />
        <MetricCard title="Distinct Errors" value={distinctErrors} color="text-warn" />
        <MetricCard
          title="Top Category"
          value={summary?.by_category?.[0]?.error_category || '-'}
          subtitle={summary?.by_category?.[0]?.total_count ? `${summary.by_category[0].total_count} hits` : ''}
          color="text-unhealthy"
        />
        <MetricCard
          title="Top Status Code"
          value={summary?.by_status_code?.[0]?.status_code || '-'}
          subtitle={summary?.by_status_code?.[0]?.total_count ? `${summary.by_status_code[0].total_count} hits` : ''}
          color="text-warn"
        />
      </div>

      {/* By category */}
      {summary?.by_category && summary.by_category.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Errors by Category</h2>
          <div className="space-y-2">
            {summary.by_category.map((cat, idx) => (
              <div key={idx} className="flex items-center gap-3">
                <span className="text-xs text-muted w-32">{cat.error_category}</span>
                <div className="flex-1 bg-border rounded-full h-2">
                  <div
                    className="h-2 rounded-full bg-unhealthy"
                    style={{ width: `${Math.min((cat.total_count / totalErrors) * 100, 100)}%` }}
                  />
                </div>
                <span className="text-xs text-muted w-20 text-right">{cat.total_count} hits</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top failing paths */}
      <div className="bg-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Top Failing Paths</h2>
        {errors.length === 0 ? (
          <p className="text-muted text-sm">No user errors recorded</p>
        ) : (
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
                {errors.map((err, idx) => (
                  <tr key={err.id || idx} className="border-b border-border/50">
                    <td className="py-2 pr-4 text-xs font-mono max-w-xs truncate">{err.path}</td>
                    <td className="py-2 pr-4 text-xs">{err.method || '-'}</td>
                    <td className="py-2 pr-4 text-unhealthy text-xs">{err.status_code}</td>
                    <td className="py-2 pr-4 text-xs">{err.error_category}</td>
                    <td className="py-2 pr-4 text-xs">{err.count}</td>
                    <td className="py-2 text-xs text-muted">
                      {err.last_seen ? err.last_seen.slice(0, 16) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

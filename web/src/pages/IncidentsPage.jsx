import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import SeverityBadge from '../components/SeverityBadge';

export default function IncidentsPage() {
  const navigate = useNavigate();
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('open');

  useEffect(() => {
    async function load() {
      const data = await api.getIncidents(filter !== 'all' ? filter : null);
      setIncidents(data || []);
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [filter]);

  if (loading) return <div className="p-6 text-muted">Loading incidents...</div>;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Incidents</h1>
          <p className="text-sm text-muted">Active and past incidents</p>
        </div>
        <div className="flex gap-1 bg-card border border-border rounded-lg p-1">
          {['open', 'resolved', 'all'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded text-xs transition-colors ${
                filter === f
                  ? 'bg-accent text-white'
                  : 'text-muted hover:text-white'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {incidents.length === 0 ? (
        <p className="text-muted text-sm">No incidents found</p>
      ) : (
        <div className="space-y-3">
          {incidents.map((inc) => (
            <div
              key={inc.id}
              onClick={() => navigate(`/incidents/${inc.id}`)}
              className="bg-card border border-border rounded-lg p-4 cursor-pointer hover:bg-white/[0.03] transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-white">{inc.title}</h3>
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={inc.severity} />
                  <StatusBadge status={inc.status} />
                </div>
              </div>
              <div className="flex items-center gap-4 text-xs text-muted">
                {inc.deployment?.slug && <span>{inc.deployment.slug}</span>}
                <span>{inc.environment}</span>
                <span>{inc.trigger_type}</span>
                <span>{inc.started_at?.slice(0, 16)}</span>
              </div>
              {inc.suggested_fix && (
                <p className="text-xs text-accent mt-2 bg-accent/10 rounded p-2 line-clamp-2">
                  Fix: {inc.suggested_fix}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

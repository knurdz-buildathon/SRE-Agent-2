import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import SeverityBadge from '../components/SeverityBadge';

export default function IncidentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [incident, setIncident] = useState(null);

  useEffect(() => {
    async function load() {
      const data = await api.getIncident(parseInt(id));
      setIncident(data);
    }
    load();
  }, [id]);

  if (!incident) return <div className="p-6 text-muted">Loading incident...</div>;
  if (incident.error) return <div className="p-6 text-unhealthy">{incident.error}</div>;

  return (
    <div className="p-6 space-y-6">
      <button
        onClick={() => navigate('/incidents')}
        className="text-muted hover:text-white text-sm flex items-center gap-1"
      >
        ← Back to Incidents
      </button>

      {/* Header */}
      <div className="bg-card border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-lg font-bold text-white">{incident.title}</h1>
          <div className="flex items-center gap-2">
            <SeverityBadge severity={incident.severity} />
            <StatusBadge status={incident.status} />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-muted text-xs">Environment</p>
            <p className="text-white">{incident.environment}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Trigger Type</p>
            <p className="text-white">{incident.trigger_type || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Error Category</p>
            <p className="text-white">{incident.error_category || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Started</p>
            <p className="text-white">{incident.started_at?.slice(0, 19) || '-'}</p>
          </div>
          <div>
            <p className="text-muted text-xs">Resolved</p>
            <p className="text-white">{incident.resolved_at?.slice(0, 19) || '-'}</p>
          </div>
          {incident.deployment && (
            <div>
              <p className="text-muted text-xs">Deployment</p>
              <p className="text-accent cursor-pointer" onClick={() => navigate(`/deployment/${incident.deployment.id}`)}>
                {incident.deployment.slug}
              </p>
            </div>
          )}
        </div>

        {incident.suggested_fix && (
          <div className="mt-4 bg-accent/10 border border-accent/20 rounded-lg p-4">
            <p className="text-xs text-accent font-medium mb-1">Suggested Fix</p>
            <p className="text-sm text-gray-200">{incident.suggested_fix}</p>
          </div>
        )}
      </div>

      {/* Timeline */}
      <div className="bg-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Timeline</h2>
        {(!incident.timeline || incident.timeline.length === 0) ? (
          <p className="text-muted text-sm">No timeline events</p>
        ) : (
          <div className="space-y-3">
            {incident.timeline.map((event) => (
              <div key={event.id} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-2.5 h-2.5 rounded-full mt-1 ${
                      event.event_type === 'opened'
                        ? 'bg-unhealthy'
                        : event.event_type === 'resolved'
                        ? 'bg-healthy'
                        : 'bg-warn'
                    }`}
                  />
                  <div className="w-px flex-1 bg-border" />
                </div>
                <div className="pb-4">
                  <p className="text-sm text-white">{event.message}</p>
                  <p className="text-xs text-muted mt-0.5">
                    {event.event_type} · {event.occurred_at?.slice(0, 19) || '-'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

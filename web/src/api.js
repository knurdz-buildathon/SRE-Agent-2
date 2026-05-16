const API_BASE = '/api';

async function fetchAPI(path) {
  try {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) {
      throw new Error(`API error: ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`API fetch failed for ${path}:`, err);
    return null;
  }
}

export const api = {
  getOverview: () => fetchAPI('/overview'),
  getDeploymentHealth: (id, limit = 50) => fetchAPI(`/deployments/${id}/health?limit=${limit}`),
  getDeploymentErrors: (id) => fetchAPI(`/deployments/${id}/errors`),
  getDeploymentStats: (id, hours = 24) => fetchAPI(`/deployments/${id}/stats?hours=${hours}`),
  getDeploymentUptime: (id, days = 30) => fetchAPI(`/deployments/${id}/uptime?days=${days}`),
  getDeploymentEnvIssues: (id) => fetchAPI(`/deployments/${id}/env-issues`),
  getDeploymentUserErrors: (id) => fetchAPI(`/deployments/${id}/user-errors`),
  getIncidents: (status, severity) => {
    let path = '/incidents';
    const params = [];
    if (status) params.push(`status=${status}`);
    if (severity) params.push(`severity=${severity}`);
    if (params.length) path += `?${params.join('&')}`;
    return fetchAPI(path);
  },
  getIncident: (id) => fetchAPI(`/incidents/${id}`),
  getErrors: () => fetchAPI('/errors'),
  getUserErrors: () => fetchAPI('/user-errors'),
  getUserErrorsSummary: () => fetchAPI('/user-errors/summary'),
  getInfrastructure: () => fetchAPI('/infrastructure'),
};

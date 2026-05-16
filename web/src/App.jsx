import React from 'react';
import { Routes, Route, NavLink } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  Server,
  AlertCircle,
  LayoutDashboard,
} from 'lucide-react';

import OverviewPage from './pages/OverviewPage';
import DeploymentPage from './pages/DeploymentPage';
import IncidentsPage from './pages/IncidentsPage';
import IncidentDetailPage from './pages/IncidentDetailPage';
import InfrastructurePage from './pages/InfrastructurePage';
import UserErrorsPage from './pages/UserErrorsPage';

const navItems = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle },
  { to: '/infrastructure', label: 'Infrastructure', icon: Server },
  { to: '/user-errors', label: 'User Errors', icon: AlertCircle },
];

export default function App() {
  return (
    <div className="flex min-h-screen bg-panel">
      {/* Sidebar */}
      <aside className="w-56 bg-card border-r border-border flex flex-col">
        <div className="px-4 py-5 border-b border-border">
          <div className="flex items-center gap-2">
            <Activity className="w-6 h-6 text-accent" />
            <span className="text-lg font-bold text-white">SRE Agent</span>
          </div>
          <p className="text-xs text-muted mt-1">Monitoring Console</p>
        </div>
        <nav className="flex-1 px-2 py-4 space-y-1">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-accent/15 text-accent font-medium'
                    : 'text-muted hover:text-gray-300 hover:bg-white/5'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-border">
          <p className="text-[11px] text-muted">SRE Agent v1.0</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/deployment/:id" element={<DeploymentPage />} />
          <Route path="/incidents" element={<IncidentsPage />} />
          <Route path="/incidents/:id" element={<IncidentDetailPage />} />
          <Route path="/infrastructure" element={<InfrastructurePage />} />
          <Route path="/user-errors" element={<UserErrorsPage />} />
        </Routes>
      </main>
    </div>
  );
}

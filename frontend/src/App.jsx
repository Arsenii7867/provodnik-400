import { useSyncExternalStore } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import Layout from './components/Layout.jsx';
import { getToken, subscribeToken } from './lib/api.js';
import AnalyticsPage from './pages/AnalyticsPage.jsx';
import CatalogPage from './pages/CatalogPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import DebriefPage from './pages/DebriefPage.jsx';
import LeaderboardPage from './pages/LeaderboardPage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import PlayPage from './pages/PlayPage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';
import ScenarioMapPage from './pages/ScenarioMapPage.jsx';

function RequireAuth({ children }) {
  const token = useSyncExternalStore(subscribeToken, getToken);
  return token ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="/scenarios" element={<CatalogPage />} />
        <Route path="/scenarios/:id/map" element={<ScenarioMapPage />} />
        <Route path="/play/:runId" element={<PlayPage />} />
        <Route path="/debrief/:runId" element={<DebriefPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/leaderboard" element={<LeaderboardPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

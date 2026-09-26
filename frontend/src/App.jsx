import { Navigate, Route, Routes } from 'react-router-dom';

import Layout from './components/Layout.jsx';
import { getToken } from './lib/api.js';
import CatalogPage from './pages/CatalogPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import DebriefPage from './pages/DebriefPage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import PlayPage from './pages/PlayPage.jsx';

function RequireAuth({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />;
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
        <Route path="/play/:runId" element={<PlayPage />} />
        <Route path="/debrief/:runId" element={<DebriefPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

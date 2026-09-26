import { useEffect } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useLoad } from '../hooks/useLoad.js';
import { api, getToken, setToken } from '../lib/api.js';

// Шапка всех экранов после входа: имя, уровень, непрочитанные уведомления, навигация.
// Профиль и уведомления перечитываются при каждом переходе, чтобы после прохождения
// шапка показывала новый уровень и свежие уведомления без обновления страницы.
export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const profile = useLoad(() => api.get('/api/profile'), location.pathname);
  const notifications = useLoad(() => api.get('/api/notifications'), location.pathname);

  useEffect(() => {
    if (profile.error && !getToken()) {
      navigate('/login', { replace: true });
    }
  }, [profile.error, navigate]);

  async function logout() {
    try {
      await api.post('/api/auth/logout');
    } catch {
      // токен могли уже отозвать: выход с экрана всё равно состоится
    }
    setToken(null);
    navigate('/login', { replace: true });
  }

  const employee = profile.data;
  const unread = (notifications.data || []).filter((item) => !item.read_at).length;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand">
            Проводник 400
          </NavLink>
          <nav className="topnav">
            <NavLink to="/" end>
              Главная
            </NavLink>
            {unread > 0 && (
              <span className="unread-badge" title="Непрочитанные уведомления" aria-label={`Непрочитанных уведомлений: ${unread}`}>
                {unread}
              </span>
            )}
            <NavLink to="/scenarios">Сценарии</NavLink>
            <NavLink to="/profile">Профиль</NavLink>
            <NavLink to="/leaderboard">Лидерборд</NavLink>
            <NavLink to="/analytics">Аналитика</NavLink>
          </nav>
          <div className="topbar-user">
            {employee && (
              <span>
                <strong>{employee.display_name}</strong>
                <span className="muted">
                  {' '}
                  {employee.level.title}, {employee.xp_total} XP
                </span>
              </span>
            )}
            <button type="button" className="button button-ghost" onClick={logout}>
              Выйти
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        <Outlet context={{ profile, notifications }} />
      </main>
    </div>
  );
}

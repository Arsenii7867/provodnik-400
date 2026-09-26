import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useLoad } from '../hooks/useLoad.js';
import { api, setToken } from '../lib/api.js';
import { ROLE_TITLES } from '../lib/labels.js';

export default function LoginPage() {
  const navigate = useNavigate();
  const pinField = useRef(null);
  const [code, setCode] = useState('');
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const health = useLoad(() => api.get('/api/health'));
  const demo = useLoad(() => api.get('/api/auth/demo'));

  function pickAccount(account) {
    setCode(account.employee_code);
    setError('');
    pinField.current.focus();
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const result = await api.post('/api/auth/login', { employee_code: code.trim(), pin });
      setToken(result.token);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page page-login">
      <h1>Проводник 400</h1>
      <p className="lead">Тренажёр нештатных ситуаций для проводников ВСМ-400.</p>
      <p>
        Вы проходите ветвящиеся сценарии из практики поезда, принимаете решения под таймером и
        видите, как каждое из них меняет лояльность пассажира и рейтинг безопасности. После
        прохождения разбор объясняет каждое решение со ссылкой на стандарт или карточку ситуации.
      </p>

      <section className="login-grid">
        <div>
          <h2>Демо-профили</h2>
          <p className="muted">Нажмите на карточку, код подставится в форму. Данные синтетические.</p>
          {demo.error && <p className="error">{demo.error}</p>}
          <div className="demo-cards">
            {(demo.data || []).map((account) => (
              <button
                type="button"
                key={account.employee_code}
                className={`demo-card${account.employee_code === code ? ' demo-card-active' : ''}`}
                onClick={() => pickAccount(account)}
              >
                <span className="demo-code">{account.employee_code}</span>
                <span className="demo-name">{account.display_name}</span>
                <span className="demo-role">
                  {ROLE_TITLES[account.role] || account.role}, {account.brigade}, {account.depot}
                </span>
                <span className="muted">{account.note}</span>
              </button>
            ))}
          </div>
        </div>

        <form className="login-form" onSubmit={submit}>
          <h2>Вход</h2>
          <label>
            Код сотрудника
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            PIN
            <input
              ref={pinField}
              type="password"
              inputMode="numeric"
              value={pin}
              onChange={(event) => setPin(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <p className="muted">PIN у демо-профилей общий, по умолчанию 1234.</p>
          {error && <p className="error">{error}</p>}
          <button type="submit" className="button" disabled={busy}>
            {busy ? 'Проверяем' : 'Войти'}
          </button>
        </form>
      </section>

      <footer className="server-status">
        {health.data && (
          <span>
            Сервер {health.data.version}, сценариев: {health.data.scenarios}
          </span>
        )}
        {health.error && <span className="error">{health.error}</span>}
      </footer>
    </main>
  );
}

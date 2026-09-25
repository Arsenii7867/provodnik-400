import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { api } from './lib/api.js';

function LoginPage() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/api/health').then(setHealth).catch((err) => setError(err.message));
  }, []);

  return (
    <main className="page page-login">
      <h1>Проводник 400</h1>
      <p className="lead">Тренажёр нештатных ситуаций для проводников ВСМ-400.</p>
      <p>
        Вы проходите ветвящиеся сценарии из практики поезда, принимаете решения под таймером и
        видите, как каждое из них меняет лояльность пассажира и рейтинг безопасности. После
        прохождения разбор объясняет каждое решение со ссылкой на стандарт или карточку ситуации.
      </p>
      <p className="muted">Все сотрудники и пассажиры в тренажёре синтетические.</p>
      <footer className="server-status">
        {health && (
          <span>
            Сервер {health.version}, сценариев: {health.scenarios}
          </span>
        )}
        {error && <span className="error">{error}</span>}
      </footer>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

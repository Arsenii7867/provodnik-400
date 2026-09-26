import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import ScaleBar from '../components/ScaleBar.jsx';
import { useLoad } from '../hooks/useLoad.js';
import { api, newIdempotencyKey, startSession } from '../lib/api.js';
import { outcomeTitle, plural } from '../lib/labels.js';
import { scaleDelta } from '../lib/timer.js';

function XpBreakdown({ debrief }) {
  const parts = debrief.xp_breakdown;
  return (
    <section className="card">
      <h2>Очки опыта: {debrief.xp} XP</h2>
      <ul className="xp-parts">
        <li>
          за исход <strong>{parts.base}</strong>
        </li>
        <li>
          за шкалы <strong>{parts.scales}</strong>
        </li>
        <li>
          за решения до истечения таймера <strong>{parts.tempo}</strong>
        </li>
        <li>
          за полную цепочку ролевой модели <strong>{parts.role}</strong>
        </li>
      </ul>
      <p className="muted">
        Рейтинг прохождения {debrief.score}.
        {debrief.is_repeat && ' Повторное прохождение даёт половину очков.'}
        {debrief.expired_timers > 0 &&
          ` ${plural(debrief.expired_timers, 'таймер истёк', 'таймера истекли', 'таймеров истекли')}.`}
      </p>
    </section>
  );
}

export default function DebriefPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [startKey] = useState(newIdempotencyKey);
  const debrief = useLoad(() => api.get(`/api/runs/${runId}/debrief`), runId);

  async function playAgain() {
    setStarting(true);
    setError('');
    try {
      const run = await startSession(debrief.data.scenario_id, null, startKey);
      navigate(`/play/${run.run_id}`);
    } catch (err) {
      setError(err.message);
      setStarting(false);
    }
  }

  if (debrief.error) {
    return (
      <>
        <p className="error">{debrief.error}</p>
        <Link to="/scenarios">В каталог</Link>
      </>
    );
  }
  const data = debrief.data;
  if (!data) {
    return <p className="muted">Загружаем разбор</p>;
  }
  const levelUp = data.level_after.id !== data.level_before.id;

  return (
    <>
      <p className="muted">Разбор прохождения</p>
      <h1>{data.title}</h1>
      <section className="card debrief-summary">
        <p className="debrief-outcome">
          Исход: <strong className={`outcome outcome-${data.outcome}`}>{outcomeTitle(data.outcome)}</strong>
        </p>
        <div className="scales">
          <ScaleBar
            kind="loyalty"
            label="Лояльность пассажира"
            value={data.loyalty_final}
            delta={scaleDelta(data.loyalty_start, data.loyalty_final)}
          />
          <ScaleBar
            kind="safety"
            label="Рейтинг безопасности"
            value={data.safety_final}
            delta={scaleDelta(data.safety_start, data.safety_final)}
          />
        </div>
        <p className="muted">Дельта показана от стартовых значений сценария.</p>
        {data.ending.summary && <p>{data.ending.summary}</p>}
      </section>

      <XpBreakdown debrief={data} />

      {(levelUp || data.achievements_new.length > 0) && (
        <section className="card card-accent">
          {levelUp && (
            <p>
              Новый уровень: <strong>{data.level_after.title}</strong> (было «{data.level_before.title}»).
            </p>
          )}
          {data.achievements_new.map((item) => (
            <p key={item.id}>
              Достижение «{item.title}»: {item.description}
            </p>
          ))}
        </section>
      )}

      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" className="button" disabled={starting} onClick={playAgain}>
          Пройти снова
        </button>
        <Link className="button button-ghost" to="/scenarios">
          В каталог
        </Link>
      </div>
    </>
  );
}

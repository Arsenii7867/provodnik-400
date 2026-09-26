import { useState } from 'react';
import { Link, useNavigate, useOutletContext } from 'react-router-dom';

import { useLoad } from '../hooks/useLoad.js';
import { api } from '../lib/api.js';
import { CHALLENGE_STATUSES, NOTIFICATION_KINDS, formatDate, formatDateTime, outcomeTitle, plural } from '../lib/labels.js';

function LevelCard({ profile }) {
  const { level } = profile;
  const span = level.next_threshold === null ? 0 : level.next_threshold - level.threshold;
  const share = span ? Math.min(1, (profile.xp_total - level.threshold) / span) : 1;
  return (
    <section className="card">
      <h2>Уровень: {level.title}</h2>
      <div className="xp-bar" role="progressbar" aria-valuenow={profile.xp_total}>
        <div className="xp-bar-fill" style={{ width: `${Math.round(share * 100)}%` }} />
      </div>
      <p>
        {profile.xp_total} XP всего.{' '}
        {level.next_threshold === null
          ? 'Это высший уровень.'
          : `До уровня «${level.next_title}» ещё ${profile.xp_to_next} XP.`}
      </p>
      <ul className="stats">
        <li>{plural(profile.runs_count, 'прохождение', 'прохождения', 'прохождений')}</li>
        <li>
          достижений {profile.achievements_count} из {profile.achievements_total}
        </li>
        {profile.rank_brigade !== null && <li>место в бригаде {profile.rank_brigade}</li>}
      </ul>
      <Link to="/profile">Профиль и достижения</Link>
    </section>
  );
}

function ActiveRunCard({ active }) {
  const navigate = useNavigate();
  return (
    <section className="card card-accent">
      <h2>Активное прохождение</h2>
      <p>
        «{active.title}», ход {active.step_no}. Сценарий ждёт вашего решения.
      </p>
      <button type="button" className="button" onClick={() => navigate(`/play/${active.run_id}`)}>
        Продолжить
      </button>
    </section>
  );
}

function LastRunCard({ lastRun }) {
  if (!lastRun) {
    return (
      <section className="card">
        <h2>Последний результат</h2>
        <p className="muted">Прохождений пока нет.</p>
        <Link className="button" to="/scenarios">
          Выбрать сценарий
        </Link>
      </section>
    );
  }
  return (
    <section className="card">
      <h2>Последний результат</h2>
      <p>
        «{lastRun.title}»: <strong className={`outcome outcome-${lastRun.outcome}`}>{outcomeTitle(lastRun.outcome)}</strong>,
        +{lastRun.xp} XP, {formatDateTime(lastRun.finished_at)}.
      </p>
      <Link to={`/debrief/${lastRun.run_id}`}>Открыть разбор</Link>
    </section>
  );
}

function RecommendedCard({ analytics }) {
  const items = (analytics.data && analytics.data.recommendations) || [];
  return (
    <section className="card">
      <h2>Рекомендовано</h2>
      {analytics.error && <p className="error">{analytics.error}</p>}
      {analytics.data && items.length === 0 && <p className="muted">Рекомендаций пока нет.</p>}
      <ul className="recommendations">
        {items.map((item) => (
          <li key={item.scenario_id}>
            <Link to={`/scenarios#${item.scenario_id}`}>{item.title}</Link>
            <span className="muted">{item.reason}</span>
          </li>
        ))}
      </ul>
      {analytics.data && (
        <Link to="/analytics">Аналитика компетенций</Link>
      )}
    </section>
  );
}

function ChallengesCard({ challenges }) {
  const items = challenges.data || [];
  return (
    <section className="card">
      <h2>Челленджи</h2>
      {challenges.error && <p className="error">{challenges.error}</p>}
      {challenges.data && items.length === 0 && <p className="muted">Открытых челленджей нет.</p>}
      <ul className="challenges">
        {items.map((item) => {
          const share = item.progress.total ? item.progress.done / item.progress.total : 0;
          return (
            <li key={item.id} className={`challenge challenge-${item.status}`}>
              <div className="card-head">
                <strong>{item.title}</strong>
                <span className="badge">{CHALLENGE_STATUSES[item.status] || item.status}</span>
              </div>
              <p>{item.description}</p>
              <div className="xp-bar" role="progressbar" aria-valuenow={item.progress.done} aria-valuemax={item.progress.total}>
                <div className="xp-bar-fill" style={{ width: `${Math.round(share * 100)}%` }} />
              </div>
              <p className="muted">
                Выполнено {item.progress.done} из {item.progress.total}, окно до {formatDate(item.ends_at)}. Бонус{' '}
                {plural(item.bonus_points, 'балл', 'балла', 'баллов')} к рейтингу
                {item.bonus_expires_at ? `, сгорает ${formatDateTime(item.bonus_expires_at)}` : ' со сроком сгорания после выполнения'}.
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function BonusCard({ bonus }) {
  if (!bonus.active_total && bonus.expiring.length === 0) {
    return null;
  }
  return (
    <section className="card">
      <h2>Бонусные баллы</h2>
      <p>Действует {plural(bonus.active_total, 'балл', 'балла', 'баллов')} сверх рейтинга.</p>
      {bonus.expiring.map((item) => (
        <p key={`${item.reason}-${item.expires_at}`} className="expiring">
          Сгорает {plural(item.points, 'балл', 'балла', 'баллов')} {formatDateTime(item.expires_at)}: {item.reason}.
        </p>
      ))}
      <Link to="/leaderboard">Лидерборд</Link>
    </section>
  );
}

function Notifications({ notifications }) {
  const [error, setError] = useState('');
  const items = notifications.data || [];
  const unread = items.filter((item) => !item.read_at);

  async function markRead(id) {
    try {
      const updated = await api.post(`/api/notifications/${id}/read`);
      notifications.setData(items.map((item) => (item.id === id ? updated : item)));
      setError('');
    } catch (err) {
      setError(err.message);
    }
  }

  async function markAll() {
    try {
      await api.post('/api/notifications/read-all');
      notifications.reload();
      setError('');
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Уведомления{unread.length > 0 && <span className="unread-badge">{unread.length}</span>}</h2>
        {unread.length > 0 && (
          <button type="button" className="button button-ghost" onClick={markAll}>
            Прочитать все
          </button>
        )}
      </div>
      {notifications.error && <p className="error">{notifications.error}</p>}
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="muted">Уведомлений пока нет.</p>}
      <ul className="notifications">
        {items.map((item) => (
          <li key={item.id} className={item.read_at ? 'notification' : 'notification notification-unread'}>
            <span className="notification-kind">{NOTIFICATION_KINDS[item.kind] || item.kind}</span>
            <strong>{item.title}</strong>
            <span>{item.body}</span>
            <span className="muted">{formatDateTime(item.created_at)}</span>
            {!item.read_at && (
              <button type="button" className="button button-ghost" onClick={() => markRead(item.id)}>
                Прочитать
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function DashboardPage() {
  const { profile, notifications } = useOutletContext();
  const active = useLoad(() => api.get('/api/sessions/active'));
  const challenges = useLoad(() => api.get('/api/challenges'));
  const analytics = useLoad(() => api.get('/api/analytics/me'));

  if (profile.error) {
    return <p className="error">{profile.error}</p>;
  }
  if (!profile.data) {
    return <p className="muted">Загружаем профиль</p>;
  }
  return (
    <>
      <h1>Мой прогресс</h1>
      <div className="cards">
        {active.data && active.data.active && <ActiveRunCard active={active.data.active} />}
        <LevelCard profile={profile.data} />
        <LastRunCard lastRun={profile.data.last_run} />
        <RecommendedCard analytics={analytics} />
        <ChallengesCard challenges={challenges} />
        <BonusCard bonus={profile.data.bonus} />
        <Notifications notifications={notifications} />
      </div>
    </>
  );
}

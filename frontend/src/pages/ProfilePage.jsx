import { Link, useOutletContext } from 'react-router-dom';

import { useLoad } from '../hooks/useLoad.js';
import { api } from '../lib/api.js';
import {
  ROLE_TITLES,
  STATUS_EXPLANATIONS,
  formatDate,
  formatDateTime,
  outcomeTitle,
  percent,
  plural,
  statusTitle,
} from '../lib/labels.js';

function LevelCard({ profile }) {
  const { level } = profile;
  const span = level.next_threshold === null ? 0 : level.next_threshold - level.threshold;
  const share = span ? Math.min(1, (profile.xp_total - level.threshold) / span) : 1;
  return (
    <section className="card">
      <h2>{profile.display_name}</h2>
      <p className="muted">
        {ROLE_TITLES[profile.role] || profile.role}, бригада {profile.brigade}, {profile.depot}, код {profile.employee_code}
      </p>
      <p>
        Уровень <strong>{level.title}</strong>, {profile.xp_total} XP.{' '}
        {level.next_threshold === null
          ? 'Это высший уровень.'
          : `Порог уровня «${level.next_title}» ${level.next_threshold} XP, осталось ${profile.xp_to_next}.`}
      </p>
      <div className="xp-bar" role="progressbar" aria-valuenow={profile.xp_total}>
        <div className="xp-bar-fill" style={{ width: `${Math.round(share * 100)}%` }} />
      </div>
      <ul className="stats">
        <li>{plural(profile.runs_count, 'прохождение', 'прохождения', 'прохождений')}</li>
        <li>
          достижений {profile.achievements_count} из {profile.achievements_total}
        </li>
        <li>
          {profile.rank_brigade === null
            ? 'в рейтинге бригады не участвует'
            : `место в бригаде ${profile.rank_brigade}`}
        </li>
      </ul>
    </section>
  );
}

function Competencies({ items }) {
  return (
    <section className="card">
      <h2>Компетенции</h2>
      <ul className="competency-list">
        {items.map((item) => (
          <li key={item.code} className={`competency-row status-${item.status}`}>
            <div className="competency-head">
              <span className="competency-title">{item.title}</span>
              <span className="competency-value">{item.mastery === null ? 'не оценивалась' : percent(item.mastery)}</span>
              <span className="competency-status" title={STATUS_EXPLANATIONS[item.status]}>
                {statusTitle(item.status)}
              </span>
            </div>
            <div className="scale-track">
              <div className="scale-fill" style={{ width: `${Math.round((item.mastery || 0) * 100)}%` }} />
            </div>
            <span className="muted competency-note">
              {item.runs_assessed > 0
                ? `оценено в ${plural(item.runs_assessed, 'сценарии', 'сценариях', 'сценариях')}: ${item.earned} из ${item.assessed} возможных очков`
                : 'ни в одном пройденном сценарии не оценивалась'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Achievements({ items }) {
  return (
    <section className="card">
      <h2>Достижения</h2>
      <ul className="achievements">
        {items.map((item) => (
          <li key={item.id} className={item.earned ? 'achievement achievement-earned' : 'achievement achievement-locked'}>
            <strong>{item.title}</strong>
            <span>{item.description}</span>
            {item.earned ? (
              <span className="muted">получено {formatDate(item.earned_at)}</span>
            ) : (
              <span className="achievement-rule">Правило: {item.rule_text}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function statusCell(run) {
  if (run.status === 'active') {
    return <Link to={`/play/${run.run_id}`}>идёт, продолжить</Link>;
  }
  if (run.status === 'abandoned') {
    return <span className="muted">прервано</span>;
  }
  return <strong className={`outcome outcome-${run.outcome}`}>{outcomeTitle(run.outcome)}</strong>;
}

function RunsHistory({ runs, classes }) {
  if (runs.length === 0) {
    return (
      <section className="card">
        <h2>История прохождений</h2>
        <p className="muted">Прохождений пока нет.</p>
      </section>
    );
  }
  return (
    <section className="card">
      <h2>История прохождений</h2>
      <div className="table-wrap">
        <table className="runs-table">
          <thead>
            <tr>
              <th>Когда</th>
              <th>Сценарий</th>
              <th>Класс</th>
              <th>Исход</th>
              <th>Лояльность</th>
              <th>Безопасность</th>
              <th>Рейтинг</th>
              <th>XP</th>
              <th>Таймеры истекли</th>
              <th>Разбор</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id}>
                <td>{formatDateTime(run.finished_at || run.started_at)}</td>
                <td>{run.title}</td>
                <td>{classes[run.service_class] || run.service_class}</td>
                <td>{statusCell(run)}</td>
                <td>{run.loyalty_final === null ? '' : run.loyalty_final}</td>
                <td>{run.safety_final === null ? '' : run.safety_final}</td>
                <td>{run.score === null ? '' : run.score}</td>
                <td>{run.xp === null ? '' : run.xp}</td>
                <td>{run.expired_timers || ''}</td>
                <td>{run.status === 'finished' && <Link to={`/debrief/${run.run_id}`}>открыть</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function ProfilePage() {
  const { profile } = useOutletContext();
  const achievements = useLoad(() => api.get('/api/achievements'));
  const runs = useLoad(() => api.get('/api/profile/runs'));
  const filters = useLoad(() => api.get('/api/scenarios/filters'));

  if (profile.error) {
    return <p className="error">{profile.error}</p>;
  }
  if (!profile.data) {
    return <p className="muted">Загружаем профиль</p>;
  }
  const classes = {};
  for (const item of (filters.data && filters.data.classes) || []) {
    classes[item.code] = item.title;
  }
  return (
    <>
      <h1>Профиль</h1>
      <div className="cards">
        <LevelCard profile={profile.data} />
        <Competencies items={profile.data.competencies} />
        {achievements.error && <p className="error">{achievements.error}</p>}
        {achievements.data && <Achievements items={achievements.data} />}
        {runs.error && <p className="error">{runs.error}</p>}
        {runs.data && <RunsHistory runs={runs.data} classes={classes} />}
      </div>
    </>
  );
}

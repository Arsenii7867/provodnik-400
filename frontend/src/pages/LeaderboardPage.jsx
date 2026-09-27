import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';

import LoadError from '../components/LoadError.jsx';
import { useLoad } from '../hooks/useLoad.js';
import { api } from '../lib/api.js';
import { SCOPES, formatDateTime, plural } from '../lib/labels.js';

function Row({ row, scope, pinned }) {
  const classes = ['board-row'];
  if (row.is_me) {
    classes.push('board-me');
  }
  if (pinned) {
    classes.push('board-pinned');
  }
  return (
    <tr className={classes.join(' ')}>
      <td className="board-rank">{row.rank}</td>
      <td>
        <strong>{row.display_name}</strong>
        <span className="muted board-code"> {row.employee_code}</span>
        {row.is_me && <span className="badge board-you">это вы</span>}
      </td>
      {scope !== 'brigade' && <td>{row.brigade}</td>}
      {scope === 'company' && <td>{row.depot}</td>}
      <td className="board-score">{row.score}</td>
      <td>
        {row.bonus_points > 0 && (
          <span className="board-bonus" title="Бонусы челленджей входят в рейтинг до срока сгорания">
            +{row.bonus_points}
          </span>
        )}
      </td>
      <td>{row.achievements}</td>
    </tr>
  );
}

export default function LeaderboardPage() {
  const { profile } = useOutletContext();
  const [scope, setScope] = useState('brigade');
  const board = useLoad(() => api.get(`/api/leaderboard?scope=${scope}`), scope);
  const data = board.data;
  const rows = (data && data.rows) || [];
  const me = data ? data.me : null;
  const pinned = me !== null && me !== undefined && !rows.some((row) => row.is_me);
  const columns = 5 + (scope !== 'brigade' ? 1 : 0) + (scope === 'company' ? 1 : 0);
  const expiring = (profile.data && profile.data.bonus && profile.data.bonus.expiring) || [];

  return (
    <>
      <h1>Лидерборд</h1>
      <div className="scope-switch" role="group" aria-label="Охват рейтинга">
        {SCOPES.map((item) => (
          <button
            key={item.code}
            type="button"
            className={item.code === scope ? 'button' : 'button button-ghost'}
            aria-pressed={item.code === scope}
            onClick={() => setScope(item.code)}
          >
            {item.title}
          </button>
        ))}
      </div>
      <p className="muted">
        Рейтинг это сумма лучших результатов по каждому сценарию плюс действующие бонусы челленджей; сгоревшие
        бонусы из суммы выпадают.
      </p>
      <LoadError resource={board} label="рейтинг" />
      <LoadError resource={profile} label="профиль" />
      {data && (
        <section className="card">
          <h2 className="scope-title">{data.scope_title}</h2>
          <div className="table-wrap">
            <table className="board">
              <thead>
                <tr>
                  <th>Место</th>
                  <th>Сотрудник</th>
                  {scope !== 'brigade' && <th>Бригада</th>}
                  {scope === 'company' && <th>Депо</th>}
                  <th>Рейтинг</th>
                  <th>Бонусы</th>
                  <th>Достижения</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <Row key={row.employee_code} row={row} scope={scope} />
                ))}
                {pinned && (
                  <>
                    <tr className="board-gap">
                      <td colSpan={columns}>ваша строка ниже первой двадцатки</td>
                    </tr>
                    <Row row={me} scope={scope} pinned />
                  </>
                )}
              </tbody>
            </table>
          </div>
          {rows.length === 0 && <p className="muted">В этом охвате пока нет проводников с результатами.</p>}
          {me === null && <p className="muted">Наставник в рейтинге не участвует, в таблице только проводники.</p>}
          {me && me.bonus_points > 0 && (
            <p className="expiring">
              В вашем рейтинге {plural(me.bonus_points, 'бонусный балл', 'бонусных балла', 'бонусных баллов')} челленджей.
              {expiring.map(
                (item) => ` Из них ${plural(item.points, 'балл сгорает', 'балла сгорают', 'баллов сгорают')} ${formatDateTime(item.expires_at)}.`,
              )}
            </p>
          )}
        </section>
      )}
    </>
  );
}

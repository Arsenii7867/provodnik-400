import { useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';

import Radar from '../components/Radar.jsx';
import WeeklyBars from '../components/WeeklyBars.jsx';
import { useLoad } from '../hooks/useLoad.js';
import { api } from '../lib/api.js';
import { STATUS_EXPLANATIONS, formatDateTime, percent, plural, seconds, statusTitle } from '../lib/labels.js';

// подпись справа от значения приходит готовой: у личной аналитики это статус сервера,
// у бригады счётчики проседающих и пробелов, чтобы фронт не выдумывал пороги
function CompetencyRadar({ items, caption }) {
  return (
    <div className="radar-wrap">
      <Radar items={items} />
      <div>
        {caption && <p className="muted">{caption}</p>}
        <ul className="radar-legend">
          {items.map((item) => (
            <li key={item.code} className={`status-${item.status}`}>
              <span className="legend-dot" />
              <span className="legend-title">{item.title}</span>
              <span className="legend-value">{item.value === null ? 'не оценивалась' : percent(item.value)}</span>
              <span className="muted" title={item.hint}>
                {item.detail}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function StatusGroup({ title, codes, titles, status, empty }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {codes.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <>
          <ul className="status-list">
            {codes.map((code) => (
              <li key={code} className={`status-${status}`}>
                {titles[code] || code}
              </li>
            ))}
          </ul>
          <p className="muted">{STATUS_EXPLANATIONS[status]}.</p>
        </>
      )}
    </section>
  );
}

function Recommendations({ items, title }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="muted">Рекомендаций пока нет.</p>
      ) : (
        <ul className="recommendations">
          {items.map((item) => (
            <li key={item.scenario_id}>
              <Link to={`/scenarios#${item.scenario_id}`}>{item.title}</Link>
              <span className="muted">{item.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function tempoText(tempo) {
  if (tempo.answered_avg_seconds === null) {
    return 'Решений под таймером ещё не было.';
  }
  const total = tempo.timers_answered + tempo.timers_expired;
  return `В среднем ${seconds(tempo.answered_avg_seconds)} на решение под таймером; вовремя ${tempo.timers_answered} из ${plural(total, 'таймера', 'таймеров', 'таймеров')} (${percent(tempo.on_time_share)}).`;
}

function escalationText(escalation) {
  if (escalation.critical_runs === 0) {
    return 'Критические сценарии ещё не пройдены, своевременность вызова бригады оценить нечем.';
  }
  const needless = escalation.needless > 0 ? `, лишних вызовов ${escalation.needless}` : '';
  return `В критических сценариях бригада вызвана вовремя в ${escalation.on_time} из ${plural(escalation.critical_runs, 'прохождения', 'прохождений', 'прохождений')} (${percent(escalation.share)})${needless}.`;
}

function PersonalAnalytics({ data, scenarioTitles }) {
  const titles = {};
  const items = data.competencies.map((item) => {
    titles[item.code] = item.title;
    return {
      code: item.code,
      title: item.title,
      value: item.mastery,
      status: item.status,
      detail: statusTitle(item.status),
      hint: STATUS_EXPLANATIONS[item.status],
    };
  });
  const fewData = data.competencies.filter((item) => item.status === 'few_data').map((item) => item.code);
  return (
    <div className="cards">
      <section className="card card-accent analytics-summary">
        <p>{data.summary}</p>
        <p className="muted">
          {plural(data.runs_total, 'завершённое прохождение', 'завершённых прохождения', 'завершённых прохождений')}
          {data.last_run_at && `, последнее ${formatDateTime(data.last_run_at)}`}.
        </p>
      </section>
      <section className="card">
        <h2>Владение компетенциями</h2>
        <CompetencyRadar
          items={items}
          caption="Владение это доля заработанных очков от возможных по последним прохождениям, где компетенция оценивалась."
        />
      </section>
      <div className="cards-row">
        <StatusGroup
          title="Проседают"
          codes={data.weak}
          titles={titles}
          status="weak"
          empty="Проседающих компетенций нет."
        />
        <StatusGroup title="Пробелы" codes={data.gaps} titles={titles} status="gap" empty="Пробелов нет: каждая компетенция хотя бы раз оценивалась." />
        <StatusGroup
          title="Мало данных"
          codes={fewData}
          titles={titles}
          status="few_data"
          empty="По каждой оценённой компетенции данных достаточно."
        />
      </div>
      <section className="card">
        <h2>Типичные ошибки</h2>
        {data.mistakes.length === 0 ? (
          <p className="muted">Ошибочных решений в последних прохождениях нет.</p>
        ) : (
          <ul className="mistakes">
            {data.mistakes.map((item) => (
              <li key={item.competency}>
                <strong>{item.title}</strong>: {plural(item.count, 'ошибочное решение', 'ошибочных решения', 'ошибочных решений')},
                последний раз в сценарии{' '}
                <Link to={`/scenarios#${item.last_scenario_id}`}>
                  «{scenarioTitles[item.last_scenario_id] || item.last_scenario_id}»
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="card">
        <h2>Динамика по неделям</h2>
        <WeeklyBars weeks={data.weekly} />
        <p className="muted">Столбец это XP за неделю, число под датой это прохождения; неделя с инцидентом выделена.</p>
      </section>
      <div className="cards-row">
        <section className="card">
          <h2>Темп решений</h2>
          <p>{tempoText(data.tempo)}</p>
        </section>
        <section className="card">
          <h2>Своевременность эскалации</h2>
          <p>{escalationText(data.escalation)}</p>
        </section>
      </div>
      <Recommendations items={data.recommendations} title="Рекомендованные сценарии" />
    </div>
  );
}

function TeamAnalytics() {
  const team = useLoad(() => api.get('/api/analytics/team'));
  if (team.error) {
    return <p className="error">{team.error}</p>;
  }
  const data = team.data;
  if (!data) {
    return <p className="muted">Загружаем аналитику бригады</p>;
  }
  const titles = {};
  const size = data.members.length;
  const items = data.competencies.map((item) => {
    titles[item.code] = item.title;
    // пробел бригады решает сервер; остальное показываем счётчиками, без своих порогов
    return {
      code: item.code,
      title: item.title,
      value: item.mean_mastery,
      status: data.brigade_gaps.includes(item.code) ? 'gap' : 'ok',
      detail: `проседает у ${item.weak_count} из ${size}, пробел у ${item.gap_count} из ${size}`,
      hint: STATUS_EXPLANATIONS.gap,
    };
  });
  return (
    <div className="cards">
      <section className="card card-accent analytics-summary">
        <p>{data.summary}</p>
      </section>
      <section className="card">
        <h2>
          Бригада {data.brigade.name}, {data.brigade.depot}
        </h2>
        <CompetencyRadar items={items} caption="Среднее владение по проводникам бригады; пробел бригады это компетенция, которую не оценивали у половины и больше." />
        <div className="table-wrap">
          <table className="team-table">
            <thead>
              <tr>
                <th>Компетенция</th>
                <th>Среднее владение</th>
                <th>Проседает у</th>
                <th>Пробел у</th>
              </tr>
            </thead>
            <tbody>
              {data.competencies.map((item) => (
                <tr key={item.code} className={data.brigade_gaps.includes(item.code) ? 'status-gap' : ''}>
                  <td>{item.title}</td>
                  <td>{item.mean_mastery === null ? 'не оценивалась' : percent(item.mean_mastery)}</td>
                  <td>{item.weak_count}</td>
                  <td>{item.gap_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <h2>Проводники</h2>
        <div className="table-wrap">
          <table className="team-table">
            <thead>
              <tr>
                <th>Сотрудник</th>
                <th>XP</th>
                <th>Прохождений</th>
                <th>Инцидентов</th>
                <th>Проседает</th>
                <th>Пробелы</th>
                <th>Последнее прохождение</th>
              </tr>
            </thead>
            <tbody>
              {data.members.map((member) => (
                <tr key={member.employee_code}>
                  <td>
                    <strong>{member.display_name}</strong>
                    <span className="muted board-code"> {member.employee_code}</span>
                  </td>
                  <td>{member.xp_total}</td>
                  <td>{member.runs}</td>
                  <td className={member.incidents > 0 ? 'cell-danger' : ''}>{member.incidents}</td>
                  <td>{member.weak.map((code) => titles[code] || code).join(', ')}</td>
                  <td>{member.gaps.map((code) => titles[code] || code).join(', ')}</td>
                  <td>{member.last_run_at ? formatDateTime(member.last_run_at) : 'ещё не проходил'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Recommendations items={data.recommendations} title="Рекомендации бригаде" />
    </div>
  );
}

export default function AnalyticsPage() {
  const { profile } = useOutletContext();
  const [chosen, setTab] = useState(null);
  const analytics = useLoad(() => api.get('/api/analytics/me'));
  const scenarios = useLoad(() => api.get('/api/scenarios'));
  const isMentor = Boolean(profile.data && profile.data.role === 'mentor');
  // наставник приходит за агрегатом по бригаде, поэтому его вкладка открывается первой
  const tab = chosen || (isMentor ? 'team' : 'me');
  const scenarioTitles = {};
  for (const item of scenarios.data || []) {
    scenarioTitles[item.id] = item.title;
  }
  return (
    <>
      <h1>Аналитика</h1>
      {isMentor && (
        <div className="scope-switch" role="group" aria-label="Раздел аналитики">
          <button
            type="button"
            className={tab === 'me' ? 'button' : 'button button-ghost'}
            aria-pressed={tab === 'me'}
            onClick={() => setTab('me')}
          >
            Мои показатели
          </button>
          <button
            type="button"
            className={tab === 'team' ? 'button' : 'button button-ghost'}
            aria-pressed={tab === 'team'}
            onClick={() => setTab('team')}
          >
            Бригада
          </button>
        </div>
      )}
      {tab === 'team' && isMentor ? (
        <TeamAnalytics />
      ) : (
        <>
          {analytics.error && <p className="error">{analytics.error}</p>}
          {!analytics.data && !analytics.error && <p className="muted">Загружаем аналитику</p>}
          {analytics.data && <PersonalAnalytics data={analytics.data} scenarioTitles={scenarioTitles} />}
        </>
      )}
    </>
  );
}

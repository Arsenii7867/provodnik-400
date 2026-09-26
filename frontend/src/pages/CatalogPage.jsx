import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { useLoad } from '../hooks/useLoad.js';
import { api, newIdempotencyKey, startSession } from '../lib/api.js';
import { outcomeTitle, plural } from '../lib/labels.js';

const EMPTY_FILTER = { competency: '', difficulty: '', service_class: '', critical: false };

function queryString(filter) {
  const query = new URLSearchParams();
  if (filter.competency) {
    query.set('competency', filter.competency);
  }
  if (filter.difficulty) {
    query.set('difficulty', filter.difficulty);
  }
  if (filter.service_class) {
    query.set('service_class', filter.service_class);
  }
  if (filter.critical) {
    query.set('critical', 'true');
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}

function Filters({ filter, setFilter, options }) {
  const maxDifficulty = options.difficulties.length ? options.difficulties[options.difficulties.length - 1] : 0;
  return (
    <form className="filters" onSubmit={(event) => event.preventDefault()}>
      <label>
        Компетенция
        <select
          value={filter.competency}
          onChange={(event) => setFilter({ ...filter, competency: event.target.value })}
        >
          <option value="">любая</option>
          {options.competencies.map((item) => (
            <option key={item.code} value={item.code}>
              {item.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Сложность
        <select
          value={filter.difficulty}
          onChange={(event) => setFilter({ ...filter, difficulty: event.target.value })}
        >
          <option value="">любая</option>
          {options.difficulties.map((level) => (
            <option key={level} value={level}>
              {level} из {maxDifficulty}
            </option>
          ))}
        </select>
      </label>
      <label>
        Класс вагона
        <select
          value={filter.service_class}
          onChange={(event) => setFilter({ ...filter, service_class: event.target.value })}
        >
          <option value="">любой</option>
          {options.classes.map((item) => (
            <option key={item.code} value={item.code}>
              {item.title}
            </option>
          ))}
        </select>
      </label>
      <label className="filter-check">
        <input
          type="checkbox"
          checked={filter.critical}
          onChange={(event) => setFilter({ ...filter, critical: event.target.checked })}
        />
        Только критические
      </label>
    </form>
  );
}

function ScenarioCard({ scenario, classes, maxDifficulty, onStart, busy, highlighted }) {
  const [serviceClass, setServiceClass] = useState('');
  // один ключ на карточку: повтор «Начать» после сетевой ошибки вернёт уже созданное прохождение
  const [startKey] = useState(newIdempotencyKey);
  return (
    <article id={scenario.id} className={highlighted ? 'scenario-card scenario-card-target' : 'scenario-card'}>
      <div className="scenario-head">
        <h2>{scenario.title}</h2>
        <span className={`badge badge-class badge-${scenario.service_class}`}>{scenario.service_class_title}</span>
        {scenario.critical && <span className="badge badge-critical">критический</span>}
      </div>
      <p>{scenario.summary}</p>
      <ul className="scenario-meta">
        <li>сложность {scenario.difficulty} из {maxDifficulty}</li>
        <li>{plural(scenario.estimated_minutes, 'минута', 'минуты', 'минут')}</li>
        <li>{scenario.has_timers ? 'с таймером' : 'без таймера'}</li>
        <li>
          {plural(scenario.node_count, 'узел', 'узла', 'узлов')}, {plural(scenario.endings_count, 'концовка', 'концовки', 'концовок')}
        </li>
      </ul>
      <p className="muted">{scenario.competencies_titles.join(', ')}</p>
      <p className="scenario-result">
        {scenario.best_outcome ? (
          <>
            Лучший исход:{' '}
            <strong className={`outcome outcome-${scenario.best_outcome}`}>{outcomeTitle(scenario.best_outcome)}</strong>,{' '}
            {plural(scenario.runs_count, 'прохождение', 'прохождения', 'прохождений')}
          </>
        ) : (
          'Вы ещё не проходили этот сценарий'
        )}
      </p>
      <div className="scenario-actions">
        <label>
          Класс
          <select value={serviceClass} onChange={(event) => setServiceClass(event.target.value)}>
            <option value="">как в сценарии</option>
            {classes.map((item) => (
              <option key={item.code} value={item.code}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => onStart(scenario, serviceClass, startKey)}
        >
          Начать
        </button>
      </div>
      <Link className="scenario-map-link" to={`/scenarios/${scenario.id}/map`}>
        Как устроен сценарий
      </Link>
    </article>
  );
}

export default function CatalogPage() {
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [filter, setFilter] = useState(EMPTY_FILTER);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const options = useLoad(() => api.get('/api/scenarios/filters'));
  const query = queryString(filter);
  const scenarios = useLoad(() => api.get(`/api/scenarios${query}`), query);
  const active = useLoad(() => api.get('/api/sessions/active'));
  // ссылка из рекомендаций ведёт на карточку по id сценария: после загрузки списка подводим к ней
  const target = hash.slice(1);
  useEffect(() => {
    const card = target && scenarios.data ? document.getElementById(target) : null;
    if (card) {
      card.scrollIntoView({ block: 'center' });
    }
  }, [target, scenarios.data]);

  async function start(scenario, serviceClass, startKey) {
    setStarting(true);
    setError('');
    try {
      const run = await startSession(scenario.id, serviceClass, startKey);
      navigate(`/play/${run.run_id}`);
    } catch (err) {
      setError(err.message);
      setStarting(false);
    }
  }

  const filterOptions = options.data || { competencies: [], classes: [], difficulties: [] };
  const maxDifficulty = filterOptions.difficulties.length
    ? filterOptions.difficulties[filterOptions.difficulties.length - 1]
    : 0;
  const activeRun = active.data && active.data.active;
  const items = scenarios.data || [];

  return (
    <>
      <h1>Сценарии</h1>
      {activeRun && (
        <p className="notice">
          У вас есть незавершённое прохождение «{activeRun.title}».{' '}
          <Link to={`/play/${activeRun.run_id}`}>Продолжить</Link> или начать другое: тогда текущее будет прервано.
        </p>
      )}
      <Filters filter={filter} setFilter={setFilter} options={filterOptions} />
      {options.error && <p className="error">{options.error}</p>}
      {scenarios.error && <p className="error">{scenarios.error}</p>}
      {error && <p className="error">{error}</p>}
      {!scenarios.loading && items.length === 0 && <p className="muted">Под эти фильтры сценариев нет.</p>}
      <div className="scenario-grid">
        {items.map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            scenario={scenario}
            classes={filterOptions.classes}
            maxDifficulty={maxDifficulty}
            onStart={start}
            busy={starting}
            highlighted={scenario.id === target}
          />
        ))}
      </div>
    </>
  );
}

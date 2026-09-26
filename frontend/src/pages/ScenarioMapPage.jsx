import { Link, useParams } from 'react-router-dom';

import GraphSvg from '../components/GraphSvg.jsx';
import { useLoad } from '../hooks/useLoad.js';
import { api } from '../lib/api.js';
import { OUTCOME_TITLES, plural } from '../lib/labels.js';

function Stats({ data }) {
  const nodes = data.nodes;
  const endings = nodes.filter((node) => node.type === 'ending').length;
  const events = nodes.filter((node) => node.type === 'event').length;
  const timers = nodes.filter((node) => node.timer_seconds).length;
  const conditional = data.edges.filter((edge) => edge.conditional).length;
  const ranges = data.scale_ranges;
  return (
    <div className="cards-row">
      <section className="card">
        <h2>Узлы и переходы</h2>
        <ul className="stats-list">
          <li>
            {plural(nodes.length, 'узел', 'узла', 'узлов')}: {nodes.length - endings - events} с выбором, {events} с событием,{' '}
            {plural(endings, 'концовка', 'концовки', 'концовок')}
          </li>
          <li>{plural(timers, 'узел с таймером', 'узла с таймером', 'узлов с таймером')}, у каждого своя ветка истечения</li>
          <li>
            {plural(data.edges.length, 'переход', 'перехода', 'переходов')}, из них{' '}
            {plural(conditional, 'условный', 'условных', 'условных')} (зависят от флагов и шкал)
          </li>
        </ul>
      </section>
      <section className="card">
        <h2>Пути и исходы</h2>
        <p className="graph-paths">
          <strong>{plural(data.paths, 'путь', 'пути', 'путей')}</strong> от старта до концовки в классе сценария
        </p>
        <ul className="stats-list">
          {Object.entries(OUTCOME_TITLES).map(([code, title]) => (
            <li key={code}>
              <span className={`outcome outcome-${code}`}>{title}</span>: {plural(data.outcomes[code] || 0, 'путь', 'пути', 'путей')}
            </li>
          ))}
        </ul>
        <p className="muted">
          Финальная лояльность от {ranges.loyalty.min} до {ranges.loyalty.max}, безопасность от {ranges.safety.min} до{' '}
          {ranges.safety.max}.
        </p>
      </section>
    </div>
  );
}

export default function ScenarioMapPage() {
  const { id } = useParams();
  const graph = useLoad(() => api.get(`/api/scenarios/${id}/graph`), id);

  if (graph.error) {
    return (
      <>
        <p className="muted">Как устроен сценарий</p>
        <section className="card">
          <p className="error">{graph.error}</p>
          <Link className="button" to="/scenarios">
            В каталог
          </Link>
        </section>
      </>
    );
  }
  const data = graph.data;
  if (!data) {
    return <p className="muted">Загружаем карту сценария</p>;
  }
  return (
    <>
      <p className="muted">Как устроен сценарий</p>
      <h1>{data.title}</h1>
      <p>
        Сценарий живёт в одном файле <code>content/scenarios/{data.scenario_id}.yaml</code>, а база хранит только
        прогресс. Граф ниже построен сервером из этого файла: слои по глубине от стартового узла слева направо.
      </p>
      <section className="card graph-card">
        <GraphSvg nodes={data.nodes} edges={data.edges} />
        <ul className="legend">
          <li>
            <span className="legend-swatch" /> узел с выбором
          </li>
          <li>
            <span className="legend-swatch swatch-event" /> событие без выбора
          </li>
          <li>
            <span className="legend-swatch swatch-exemplary" /> концовка, чаще образцово
          </li>
          <li>
            <span className="legend-swatch swatch-acceptable" /> концовка, чаще приемлемо
          </li>
          <li>
            <span className="legend-swatch swatch-incident" /> концовка, чаще инцидент
          </li>
          <li>
            <span className="legend-swatch swatch-timer">20 с</span> таймер узла
          </li>
          <li>
            <span className="legend-line" /> ветка истечения таймера
          </li>
          <li>
            <span className="legend-line line-conditional" /> вариант по условию
          </li>
        </ul>
        <p className="muted">Наведите на узел или стрелку: подсказка называет вариант, условие и исход.</p>
      </section>
      <Stats data={data} />
      <section className="card">
        <h2>Фрагмент YAML: стартовый узел</h2>
        <pre className="yaml">{data.yaml_excerpt}</pre>
      </section>
      <section className="card">
        <h2>Развилка за три минуты</h2>
        <ol className="howto">
          <li>
            Откройте <code>content/scenarios/{data.scenario_id}.yaml</code> и добавьте в нужный узел вариант из
            восьми строк: <code>id</code>, <code>text</code>, <code>effects</code>, <code>competencies</code>,{' '}
            <code>next</code> на существующий узел и <code>debrief</code> с <code>verdict</code>, <code>why</code>,{' '}
            <code>better</code> и <code>refs</code>.
          </li>
          <li>
            Из папки <code>backend</code> запустите <code>python -m app.scenarios.validator ../content</code>: в строке
            ИТОГ должно быть ошибок=0, число путей вырастет.
          </li>
          <li>
            Сервер сравнивает время изменения файлов при каждом обращении и перечитывает сценарий сам: новая кнопка
            видна в прохождении, на этой карте появляется новая стрелка, а в разборе есть строка с её эффектом.
            Наставник может перечитать контент явно запросом на перезагрузку сценариев.
          </li>
        </ol>
        <details>
          <summary>Тот же граф в записи Mermaid для документации</summary>
          <pre className="yaml">{data.mermaid}</pre>
        </details>
      </section>
      <div className="actions">
        <Link className="button button-ghost" to="/scenarios">
          В каталог
        </Link>
      </div>
    </>
  );
}

import { useState } from 'react';
import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom';

import RefList from '../components/RefList.jsx';
import ScaleBar from '../components/ScaleBar.jsx';
import { useLoad } from '../hooks/useLoad.js';
import { api, newIdempotencyKey, startSession } from '../lib/api.js';
import {
  ESCALATION_TARGETS,
  ROLE_STEPS,
  formatDateTime,
  outcomeTitle,
  percent,
  plural,
  roleStepTitle,
  seconds,
  signed,
  statusTitle,
  verdictTitle,
} from '../lib/labels.js';
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
        {debrief.timers_answered > 0 &&
          ` Вовремя отвечено на ${plural(debrief.timers_answered, 'таймер', 'таймера', 'таймеров')}.`}
        {debrief.expired_timers > 0 &&
          ` ${plural(debrief.expired_timers, 'таймер истёк', 'таймера истекли', 'таймеров истекли')}, поэтому образцовый исход был закрыт.`}
      </p>
      <RoleChainSummary chain={debrief.role_chain} />
    </section>
  );
}

function RoleChainSummary({ chain }) {
  const done = new Set(chain.steps);
  return (
    <p className="role-chain-summary">
      Ролевая модель:{' '}
      {ROLE_STEPS.map((step) => (
        <span key={step.code} className={done.has(step.code) ? 'role-step role-step-done' : 'role-step'}>
          {step.title}
        </span>
      ))}
      <span className="muted">{chain.complete ? ' (цепочка пройдена целиком)' : ' (цепочка не завершена)'}</span>
    </p>
  );
}

function Rewards({ debrief }) {
  const levelUp = debrief.level_after.id !== debrief.level_before.id;
  const items = debrief.achievements_new;
  const challenges = debrief.challenges_completed;
  if (!levelUp && items.length === 0 && challenges.length === 0) {
    return null;
  }
  return (
    <section className="card card-accent debrief-new">
      <h2>Новое после прохождения</h2>
      {levelUp && (
        <p>
          Новый уровень: <strong>{debrief.level_after.title}</strong> (было «{debrief.level_before.title}»).
        </p>
      )}
      {items.map((item) => (
        <p key={item.id}>
          Достижение «{item.title}»: {item.description}
        </p>
      ))}
      {challenges.map((item) => (
        <p key={item.id}>
          Челлендж «{item.title}» выполнен: {plural(item.bonus_points, 'бонусный балл', 'бонусных балла', 'бонусных баллов')}{' '}
          к рейтингу, сгорают {formatDateTime(item.bonus_expires_at)}.
        </p>
      ))}
    </section>
  );
}

function CompetencyDeltas({ items }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="card">
      <h2>Компетенции в этом прохождении</h2>
      <ul className="competency-deltas">
        {items.map((item) => (
          <li key={item.code} className={`status-${item.status}`}>
            <strong>{item.title}</strong>: заработано {item.earned} из {item.assessed} возможных; владение{' '}
            {item.mastery_before === null ? 'не оценивалось' : percent(item.mastery_before)}
            {' -> '}
            {percent(item.mastery_after)} ({statusTitle(item.status)})
          </li>
        ))}
      </ul>
    </section>
  );
}

function EffectArrow({ label, before, after }) {
  const delta = scaleDelta(before, after);
  const direction = delta > 0 ? 'delta-up' : delta < 0 ? 'delta-down' : 'delta-zero';
  return (
    <div className={`effect-arrow effect-${direction}`}>
      <span className="effect-label">{label}</span>
      <span className="effect-before">{before}</span>
      <svg viewBox="0 0 28 12" width="28" height="12" aria-hidden="true">
        <path d="M2 6h20m-6-4 6 4-6 4" />
      </svg>
      <span className="effect-after">{after}</span>
      <span className={`scale-delta ${direction}`}>{signed(delta)}</span>
    </div>
  );
}

function quoted(text) {
  // реплики в сценариях часто уже начинаются с кавычки: вторую пару не добавляем
  return text.startsWith('«') ? text : `«${text}»`;
}

function timingText(step) {
  if (step.expired) {
    return `Время вышло: ${plural(step.timer_seconds || 0, 'секунда прошла', 'секунды прошли', 'секунд прошли')} без решения.`;
  }
  if (step.timer_seconds) {
    return `Ответ за ${seconds(step.answered_in_seconds)} из ${step.timer_seconds} с.`;
  }
  return step.answered_in_seconds ? `Ответ за ${seconds(step.answered_in_seconds)}.` : '';
}

function StepCard({ step, titles }) {
  const verdict = step.verdict || 'event';
  const points = Object.entries(step.competencies || {});
  const applied = step.delayed_applied || [];
  return (
    <li className={`debrief-step verdict-${verdict}${step.expired ? ' step-expired' : ''}`}>
      <div className="step-head">
        <span className="step-badge">Ход {step.step_no}</span>
        <span className={`verdict verdict-${verdict}`}>{verdictTitle(step.verdict)}</span>
        <span className="muted">{timingText(step)}</span>
      </div>
      <p className="step-situation">{step.node_text}</p>
      {step.passenger_says && <blockquote className="passenger">{step.passenger_says}</blockquote>}
      <div className="step-choice">
        <h4>{step.expired ? 'Решение не принято' : 'Ваш выбор'}</h4>
        {step.expired ? (
          <p>Варианты закрылись по таймеру, сервер повёл сценарий по ветке истечения.</p>
        ) : (
          <p>{step.option_text || 'Событие сценария: выбора здесь не было, шкалы изменил сюжет.'}</p>
        )}
        <div className="step-tags">
          {step.role_step && <span className="tag">шаг ролевой модели: {roleStepTitle(step.role_step)}</span>}
          {step.escalation_target && (
            <span className="tag">вызов: {ESCALATION_TARGETS[step.escalation_target] || step.escalation_target}</span>
          )}
          {points.map(([code, value]) => (
            <span key={code} className={`tag ${value > 0 ? 'tag-plus' : value < 0 ? 'tag-minus' : ''}`}>
              {titles[code] || code} {signed(value)}
            </span>
          ))}
        </div>
      </div>
      <div className="step-effects">
        <EffectArrow label="Лояльность" before={step.loyalty_before} after={step.loyalty_after} />
        <EffectArrow label="Безопасность" before={step.safety_before} after={step.safety_after} />
      </div>
      {applied.map((item) => (
        <p key={item.text} className={item.cancelled ? 'delayed delayed-cancelled' : 'delayed'}>
          {item.cancelled ? 'Отложенное последствие отменено: ' : 'Отложенное последствие сработало: '}
          {item.text}
          {!item.cancelled && item.effects && (
            <span>
              {' '}
              (лояльность {signed(item.effects.loyalty || 0)}, безопасность {signed(item.effects.safety || 0)})
            </span>
          )}
        </p>
      ))}
      {step.why ? (
        <div className="step-why">
          <h4>Почему</h4>
          <p>{step.why}</p>
        </div>
      ) : (
        step.verdict && (
          <p className="muted">Разбор этого хода недоступен: вариант изменён в сценарии после прохождения.</p>
        )
      )}
      {step.verdict !== 'best' && (step.better || step.best_option) && (
        <div className="step-better">
          <h4>Как лучше</h4>
          {step.better && <p>{step.better}</p>}
          {step.best_option && <p className="best-option">Лучший вариант: {quoted(step.best_option.text)}</p>}
        </div>
      )}
      <RefList refs={step.refs} />
    </li>
  );
}

export default function DebriefPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { profile } = useOutletContext();
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
  // названия компетенций для очков хода берём из профиля: сервер отдаёт только коды
  const titles = {};
  for (const item of (profile.data && profile.data.competencies) || []) {
    titles[item.code] = item.title;
  }
  for (const item of data.competencies_delta) {
    titles[item.code] = item.title;
  }

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
        <h3>{data.ending.title}</h3>
        {data.ending.text && <p>{data.ending.text}</p>}
        {data.ending.summary && <p>{data.ending.summary}</p>}
        <RefList refs={data.ending.refs} />
      </section>

      <XpBreakdown debrief={data} />
      <Rewards debrief={data} />
      <CompetencyDeltas items={data.competencies_delta} />

      <h2 className="steps-title">По шагам: {plural(data.steps.length, 'решение', 'решения', 'решений')}</h2>
      <ol className="debrief-steps">
        {data.steps.map((step) => (
          <StepCard key={step.step_no} step={step} titles={titles} />
        ))}
      </ol>

      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" className="button" disabled={starting} onClick={playAgain}>
          Пройти снова
        </button>
        <Link className="button button-ghost" to="/scenarios">
          В каталог
        </Link>
        <Link className="button button-ghost" to={`/scenarios/${data.scenario_id}/map`}>
          Как устроен сценарий
        </Link>
      </div>
    </>
  );
}

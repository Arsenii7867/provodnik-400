import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import ScaleBar from '../components/ScaleBar.jsx';
import TimerRing from '../components/TimerRing.jsx';
import { useServerClock } from '../hooks/useServerClock.js';
import { api } from '../lib/api.js';
import { ROLE_STEPS, outcomeTitle, plural, roleStepTitle, signed } from '../lib/labels.js';
import { scaleDelta } from '../lib/timer.js';

const EXPIRE_RETRIES = 5;
const SERVER_WAIT_MS = 3000;
const EXPIRED_NOTICE = 'Время вышло: решение принято без вас, сервер повёл сценарий по ветке истечения.';

// коды, при которых наше представление о прохождении устарело и его надо перечитать
const STALE_CODES = new Set(['stale_step', 'already_finished', 'run_not_active']);

function ContextBar({ context }) {
  const passenger = context.passenger || {};
  return (
    <ul className="context-bar">
      <li>
        <strong>{context.service_class_title}</strong>
        {context.layout && <span className="muted"> {context.layout}</span>}
      </li>
      {context.segment && <li>{context.segment}</li>}
      {context.next_station_minutes !== null && (
        <li>до станции {plural(context.next_station_minutes, 'минута', 'минуты', 'минут')}</li>
      )}
      {context.wait_minutes !== null && (
        <li>норматив ожидания {plural(context.wait_minutes, 'минута', 'минуты', 'минут')}</li>
      )}
      {context.time_of_day && <li>{context.time_of_day}</li>}
      {passenger.label && (
        <li>
          {passenger.label}
          {passenger.state && <span className="muted">, {passenger.state}</span>}
        </li>
      )}
    </ul>
  );
}

function RoleChain({ chain }) {
  const done = new Set(chain.steps);
  return (
    <ol className="role-chain" aria-label="Ролевая модель">
      {ROLE_STEPS.map((step) => (
        <li
          key={step.code}
          className={done.has(step.code) ? 'role-step role-step-done' : chain.next_expected === step.code ? 'role-step role-step-next' : 'role-step'}
        >
          {step.title}
        </li>
      ))}
    </ol>
  );
}

function LastStep({ step }) {
  if (!step) {
    return null;
  }
  const applied = step.delayed_applied || [];
  return (
    <div className="last-step">
      {step.expired ? (
        <p className="last-step-expired">Ход {step.step_no}: таймер истёк, сработала ветка истечения.</p>
      ) : (
        <p>
          Ход {step.step_no} принят
          {step.role_step && <span className="muted">, шаг ролевой модели «{roleStepTitle(step.role_step)}»</span>}.
        </p>
      )}
      {applied.map((item, index) => (
        <p key={`${index}-${item.text}`} className={item.cancelled ? 'delayed delayed-cancelled' : 'delayed'}>
          {item.cancelled ? 'Отложенное последствие отменено: ' : 'Отложенное последствие: '}
          {item.text}
          {!item.cancelled && item.effects && (
            <span className="muted">
              {' '}
              (лояльность {signed(item.effects.loyalty || 0)}, безопасность {signed(item.effects.safety || 0)})
            </span>
          )}
        </p>
      ))}
    </div>
  );
}

function Ending({ run }) {
  return (
    <section className="ending card">
      <p className="muted">Концовка</p>
      <h2>{run.node.title || 'Сценарий завершён'}</h2>
      <p>{run.node.text}</p>
      {run.outcome && (
        <p>
          Исход: <strong className={`outcome outcome-${run.outcome}`}>{outcomeTitle(run.outcome)}</strong>
          {run.xp !== null && <span>, начислено {run.xp} XP</span>}
        </p>
      )}
      <Link className="button" to={`/debrief/${run.run_id}`}>
        Перейти к разбору
      </Link>
    </section>
  );
}

export default function PlayPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [serverWaits, setServerWaits] = useState(false);
  const expiringStep = useRef(null);
  const earlyReports = useRef({ step: null, count: 0 });
  const remaining = useServerClock(run && run.status === 'active' ? run.deadline_at : null);

  const load = useCallback(async () => {
    const fresh = await api.get(`/api/sessions/${runId}`);
    setRun(fresh);
    return fresh;
  }, [runId]);

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [load]);

  function accept(next) {
    setRun(next);
    setNotice(next.expired ? EXPIRED_NOTICE : '');
    setServerWaits(false);
  }

  async function send(path, body) {
    setBusy(true);
    setError('');
    try {
      accept(await api.post(path, body));
    } catch (err) {
      if (STALE_CODES.has(err.code)) {
        // двойной клик или вторая вкладка ушли вперёд: показываем то, что знает сервер
        await load().catch((inner) => setError(inner.message));
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function reportExpiry(stepNo) {
    try {
      accept(await api.post(`/api/sessions/${runId}/expire`, { step_no: stepNo }));
    } catch (err) {
      if (STALE_CODES.has(err.code)) {
        await load().catch((inner) => setError(inner.message));
      } else if (err.code === 'too_early') {
        // по часам сервера время ещё есть: свежий server_now поправит смещение, и отсчёт
        // дойдёт до нуля ещё раз; после нескольких отказов подряд повторяем реже и говорим об этом
        const early = earlyReports.current;
        early.count = early.step === stepNo ? early.count + 1 : 1;
        early.step = stepNo;
        await load().catch((inner) => setError(inner.message));
        if (early.count < EXPIRE_RETRIES) {
          expiringStep.current = null;
        } else {
          setServerWaits(true);
          setTimeout(() => {
            expiringStep.current = null;
          }, SERVER_WAIT_MS);
        }
      } else {
        setError(err.message);
      }
    }
  }

  // без списка зависимостей: остаток меняется каждые 250 мс, а от повторной отправки за один
  // и тот же ход защищает expiringStep
  useEffect(() => {
    if (!run || run.status !== 'active' || !run.deadline_at || remaining !== 0 || busy) {
      return;
    }
    if (expiringStep.current === run.step_no) {
      return;
    }
    expiringStep.current = run.step_no;
    reportExpiry(run.step_no);
  });

  if (error && !run) {
    return (
      <>
        <p className="error">{error}</p>
        <Link to="/scenarios">В каталог</Link>
      </>
    );
  }
  if (!run) {
    return <p className="muted">Загружаем прохождение</p>;
  }

  const node = run.node;
  const last = run.last_step;
  const timedOut = run.status === 'active' && Boolean(run.deadline_at) && remaining === 0;
  const locked = busy || timedOut || run.status !== 'active';

  return (
    <>
      <div className="play-head">
        <div>
          <h1>{run.title}</h1>
          <ContextBar context={run.context} />
        </div>
        <span className="step-no">Ход {run.step_no + 1}</span>
      </div>

      <div className="scales">
        <ScaleBar
          kind="loyalty"
          label="Лояльность пассажира"
          value={run.loyalty}
          delta={last ? scaleDelta(last.loyalty_before, last.loyalty_after) : null}
        />
        <ScaleBar
          kind="safety"
          label="Рейтинг безопасности"
          value={run.safety}
          delta={last ? scaleDelta(last.safety_before, last.safety_after) : null}
        />
      </div>

      <LastStep step={last} />
      {notice && <p className="notice notice-expired">{notice}</p>}
      {serverWaits && <p className="notice">Сервер ещё ждёт истечения по своим часам, остаток обновится сам.</p>}
      {error && <p className="error">{error}</p>}

      {run.status === 'abandoned' && (
        <section className="card">
          <h2>Прохождение прервано</h2>
          <p className="muted">Начато другое прохождение или сценарий изменился. Выберите сценарий заново.</p>
          <Link className="button" to="/scenarios">
            В каталог
          </Link>
        </section>
      )}

      {run.status === 'finished' && <Ending run={run} />}

      {run.status === 'active' && (
        <section className={`node card${timedOut ? ' node-locked' : ''}`}>
          <div className="node-body">
            <div className="node-text">
              <p>{node.text}</p>
              {node.passenger_says && <blockquote className="passenger">{node.passenger_says}</blockquote>}
            </div>
            {run.deadline_at && <TimerRing remaining={remaining} total={node.timer_seconds} />}
          </div>

          {node.type === 'event' ? (
            <button
              type="button"
              className="button option-button"
              disabled={locked}
              onClick={() => send(`/api/sessions/${runId}/choose`, { option_id: 'continue', step_no: run.step_no })}
            >
              Далее
            </button>
          ) : (
            <div className="options">
              {node.options.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className="option-button"
                  disabled={locked}
                  onClick={() => send(`/api/sessions/${runId}/choose`, { option_id: option.id, step_no: run.step_no })}
                >
                  <span>{option.text}</span>
                  {option.role_step && <span className="option-role">{roleStepTitle(option.role_step)}</span>}
                </button>
              ))}
            </div>
          )}
          <RoleChain chain={run.role_chain} />
        </section>
      )}

      {run.status === 'active' && (
        <p className="muted play-foot">
          Таймер и исход решений проверяет сервер: поздний выбор считается истечением.{' '}
          <button type="button" className="link-button" onClick={() => navigate('/')}>
            На главную
          </button>
        </p>
      )}
    </>
  );
}

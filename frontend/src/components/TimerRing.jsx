import { formatSeconds, ringOffset } from '../lib/timer.js';

const RADIUS = 44;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const URGENT_SECONDS = 5;

// Кольцо таймера: остаток приходит из useServerClock, полная длительность из ответа сервера.
export default function TimerRing({ remaining, total }) {
  const expired = remaining === 0;
  const urgent = !expired && remaining <= URGENT_SECONDS;
  return (
    <div className={`timer-ring${expired ? ' timer-ring-expired' : urgent ? ' timer-ring-urgent' : ''}`}>
      <svg viewBox="0 0 100 100" width="104" height="104" aria-hidden="true">
        <circle className="timer-ring-track" cx="50" cy="50" r={RADIUS} />
        <circle
          className="timer-ring-progress"
          cx="50"
          cy="50"
          r={RADIUS}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={ringOffset(remaining, total, CIRCUMFERENCE)}
        />
      </svg>
      <span className="timer-ring-value">{formatSeconds(remaining)}</span>
      <span className="timer-ring-caption">{expired ? 'время вышло' : 'на решение'}</span>
    </div>
  );
}

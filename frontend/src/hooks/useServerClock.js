import { useEffect, useState } from 'react';

import { getServerOffset } from '../lib/api.js';
import { remainingSeconds } from '../lib/timer.js';

const TICK_MS = 250;

function remainingNow(deadlineAt) {
  return remainingSeconds(deadlineAt, Date.now(), getServerOffset());
}

// Остаток до дедлайна по часам сервера: смещение берётся из последнего ответа API.
// Клиент только показывает секунды; истечение и поздний выбор решает сервер.
export function useServerClock(deadlineAt) {
  const [remaining, setRemaining] = useState(() => remainingNow(deadlineAt));

  useEffect(() => {
    setRemaining(remainingNow(deadlineAt));
    if (!deadlineAt) {
      return undefined;
    }
    const id = setInterval(() => setRemaining(remainingNow(deadlineAt)), TICK_MS);
    return () => clearInterval(id);
  }, [deadlineAt]);

  return remaining;
}

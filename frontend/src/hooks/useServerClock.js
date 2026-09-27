import { useEffect, useState } from 'react';

import { getServerOffset } from '../lib/api.js';
import { remainingSeconds } from '../lib/timer.js';

const TICK_MS = 250;

// Остаток до дедлайна по часам сервера: смещение берётся из последнего принятого замера API.
// Значение считается на каждом рендере, а интервал только заставляет перерисоваться:
// так новый узел с новым дедлайном никогда не увидит нулевой остаток прежнего узла.
// Клиент только показывает секунды; истечение и поздний выбор решает сервер.
export function useServerClock(deadlineAt) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!deadlineAt) {
      return undefined;
    }
    const id = setInterval(() => setTick((tick) => tick + 1), TICK_MS);
    return () => clearInterval(id);
  }, [deadlineAt]);

  return remainingSeconds(deadlineAt, Date.now(), getServerOffset());
}

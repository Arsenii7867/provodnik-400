// Чистые функции таймера без React. Истечение решает сервер, клиент только показывает остаток:
// часы браузера могут спешить или отставать, поэтому остаток считается через смещение
// между server_now из ответа и Date.now() в момент ответа.

export function parseServerTime(iso) {
  // сервер отдаёт микросекунды, а Date.parse надёжно читает только миллисекунды
  return Date.parse(String(iso).replace(/(\.\d{3})\d+/, '$1'));
}

export function clockOffset(serverNowIso, clientNowMs) {
  return parseServerTime(serverNowIso) - clientNowMs;
}

export function remainingMs(deadlineIso, clientNowMs, offsetMs) {
  if (!deadlineIso) {
    return null;
  }
  return Math.max(0, parseServerTime(deadlineIso) - (clientNowMs + offsetMs));
}

export function remainingSeconds(deadlineIso, clientNowMs, offsetMs) {
  const ms = remainingMs(deadlineIso, clientNowMs, offsetMs);
  return ms === null ? null : Math.ceil(ms / 1000);
}

export function formatSeconds(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

export function timerShare(remaining, total) {
  if (!total) {
    return 0;
  }
  return Math.min(1, Math.max(0, remaining / total));
}

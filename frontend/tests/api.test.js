import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';

import { api, getServerOffset, getToken, setToken, subscribeToken } from '../src/lib/api.js';
import { remainingSeconds } from '../src/lib/timer.js';

beforeEach(() => {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  };
  globalThis.window = new EventTarget();
});

afterEach(() => {
  delete globalThis.localStorage;
  delete globalThis.window;
});

const expired = () => new Response(JSON.stringify({ error: { code: 'token_expired', message: 'Войдите заново' } }), { status: 401 });

test('malformed successful JSON is reported as a response error instead of null', async (t) => {
  setToken('current');
  for (const body of ['<html>Proxy error</html>', '{"token":', '']) {
    t.mock.method(globalThis, 'fetch', async () => new Response(body, { status: 200 }));
    await assert.rejects(api.get('/api/profile'), {
      status: 200,
      code: 'invalid_response',
      message: 'Сервер вернул некорректный ответ, попробуйте ещё раз',
    });
    assert.equal(getToken(), 'current');
  }
});

test('non-JSON server errors retain their HTTP status and fallback message', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>Bad Gateway</html>', { status: 502 }));
  await assert.rejects(api.get('/api/profile'), {
    status: 502,
    code: 'http_error',
    message: 'Сервер ответил ошибкой 502',
  });
});

test('valid JSON and empty responses keep their existing contract', async (t) => {
  const responses = [
    new Response('{"ok":true}', { status: 200 }),
    new Response('null', { status: 200 }),
    new Response(null, { status: 204 }),
  ];
  t.mock.method(globalThis, 'fetch', async () => responses.shift());
  assert.deepEqual(await api.post('/api/auth/logout'), { ok: true });
  assert.equal(await api.get('/api/empty'), null);
  assert.equal(await api.get('/api/no-content'), null);
});

test('a connection dropped while reading the response remains a retryable network error', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => ({
    ok: true,
    status: 200,
    text: async () => { throw new TypeError('terminated'); },
  }));
  await assert.rejects(api.post('/api/sessions/1/expire', { step_no: 0 }), {
    code: 'network',
    status: 0,
    message: 'Сервер недоступен, попробуйте ещё раз через минуту',
  });
});

test('token invalidation and cross-tab changes notify subscribers; cleanup removes listeners', async (t) => {
  setToken('old');
  const changes = [];
  const unsubscribe = subscribeToken(() => changes.push(getToken()));
  t.mock.method(globalThis, 'fetch', async () => expired());
  await assert.rejects(api.get('/api/profile'), { code: 'token_expired' });
  assert.equal(getToken(), null);
  assert.deepEqual(changes, [null]);

  localStorage.setItem('provodnik.token', 'another-tab');
  window.dispatchEvent(new Event('storage'));
  assert.deepEqual(changes, [null, 'another-tab']);
  unsubscribe();
  setToken(null);
  window.dispatchEvent(new Event('storage'));
  assert.equal(changes.length, 2);
});

test('a delayed 401 from an old login does not invalidate a newer token', async (t) => {
  setToken('old');
  let respond;
  t.mock.method(globalThis, 'fetch', () => new Promise((resolve) => { respond = resolve; }));
  const pending = api.get('/api/profile');
  setToken('new');
  respond(expired());
  await assert.rejects(pending, { code: 'token_expired' });
  assert.equal(getToken(), 'new');
});

for (const phase of ['headers', 'body']) {
  test(`a stalled ${phase} request aborts without retrying a possibly accepted choice`, async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    setToken('current');
    let signal;
    let finish;
    const stalled = new Promise((resolve) => { finish = resolve; });
    const fetchMock = t.mock.method(globalThis, 'fetch', async (_path, init) => {
      signal = init.signal;
      if (phase === 'headers') return stalled;
      return { ok: true, status: 200, text: () => stalled };
    });
    const pending = api.post('/api/sessions/1/choose', { option_id: 'help', step_no: 0 });
    const rejected = assert.rejects(pending, {
      status: 0,
      code: 'network',
      message: 'Сервер не ответил вовремя. Обновите страницу, чтобы проверить, сохранено ли действие.',
    });
    // Let fetch resolve so the body case really is waiting on response.text().
    await Promise.resolve();
    t.mock.timers.tick(10_000);
    await rejected;
    assert.equal(signal.aborted, true);
    assert.equal(fetchMock.mock.callCount(), 1);
    assert.equal(getToken(), 'current');
    finish(phase === 'headers' ? new Response('{"ok":true}') : '{"ok":true}');
    t.mock.timers.tick(30_000);
    assert.equal(fetchMock.mock.callCount(), 1);
  });
}

test('a completed request clears its deadline instead of aborting later', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let signal;
  t.mock.method(globalThis, 'fetch', async (_path, init) => {
    signal = init.signal;
    return new Response('{"ok":true}');
  });
  assert.deepEqual(await api.get('/api/profile'), { ok: true });
  t.mock.timers.tick(30_000);
  assert.equal(signal.aborted, false);
});

const CLOCK_START = Date.parse('2026-09-27T12:00:00.000Z');
const clockResponse = (serverMs) => new Response(JSON.stringify({ server_now: new Date(serverMs).toISOString() }));

for (const phase of ['headers', 'body']) {
  test(`a delayed ${phase} response cannot rewind the active timer after a newer clock sample`, async (t) => {
    let now = CLOCK_START;
    t.mock.method(Date, 'now', () => now);
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    t.mock.method(globalThis, 'fetch', async (path) => {
      if (path === '/api/sessions/old') {
        if (phase === 'headers') return held;
        return { ok: true, status: 200, text: () => held };
      }
      return clockResponse(now + 2000);
    });
    const old = api.get('/api/sessions/old');
    await Promise.resolve();
    now += 2000;
    await api.get('/api/sessions/current');
    assert.equal(getServerOffset(), 2000);
    now += 1000;
    const deadline = new Date(CLOCK_START + 20_000).toISOString();
    assert.equal(remainingSeconds(deadline, now, getServerOffset()), 15);
    release(phase === 'headers'
      ? clockResponse(CLOCK_START + 2000)
      : JSON.stringify({ server_now: new Date(CLOCK_START + 2000).toISOString() }));
    await old;
    assert.equal(remainingSeconds(deadline, now, getServerOffset()), 15);
    assert.equal(getServerOffset(), 2000);
    // A fresh sample must still be usable after discarding a delayed response.
    t.mock.method(globalThis, 'fetch', async () => clockResponse(now + 3000));
    await api.get('/api/sessions/current');
    assert.equal(getServerOffset(), 3000);
    assert.equal(remainingSeconds(deadline, now, getServerOffset()), 14);
  });
}

for (const newer of ['network failure', 'HTTP failure', 'missing timestamp', 'invalid timestamp']) {
  test(`a newer ${newer} leaves a pending useful clock sample eligible`, async (t) => {
    t.mock.method(Date, 'now', () => CLOCK_START);
    t.mock.method(globalThis, 'fetch', async () => clockResponse(CLOCK_START + 1000));
    await api.get('/api/sessions/initial');
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    t.mock.method(globalThis, 'fetch', async (path) => {
      if (path === '/api/sessions/pending') return held;
      if (newer === 'network failure') throw new TypeError('Connection lost');
      if (newer === 'HTTP failure') return new Response('{}', { status: 503 });
      return new Response(JSON.stringify(newer === 'missing timestamp' ? { ok: true } : { server_now: 'invalid' }));
    });
    const pending = api.get('/api/sessions/pending');
    const later = api.get('/api/profile');
    if (newer.endsWith('failure')) await assert.rejects(later);
    else await later;
    // Capture the intermediate value without leaving an unresolved request on assertion failure.
    const beforeUsefulSample = getServerOffset();
    release(clockResponse(CLOCK_START + 5000));
    await pending;
    assert.equal(beforeUsefulSample, 1000);
    assert.equal(getServerOffset(), 5000);
  });
}

test('a successful response from the previous account cannot change the current clock', async (t) => {
  t.mock.method(Date, 'now', () => CLOCK_START);
  setToken('previous');
  t.mock.method(globalThis, 'fetch', async () => clockResponse(CLOCK_START + 2000));
  await api.get('/api/sessions/initial');
  let release;
  t.mock.method(globalThis, 'fetch', () => new Promise((resolve) => { release = resolve; }));
  const pending = api.get('/api/sessions/previous-account');
  setToken('current');
  const offsetAfterLogin = getServerOffset();
  release(clockResponse(CLOCK_START + 10_000));
  await pending;
  assert.equal(getToken(), 'current');
  assert.equal(getServerOffset(), offsetAfterLogin);
  t.mock.method(globalThis, 'fetch', async () => clockResponse(CLOCK_START + 3000));
  await api.get('/api/sessions/current-account');
  assert.equal(getServerOffset(), 3000);
});

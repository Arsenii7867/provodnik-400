import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';

import { api, getToken, setToken, subscribeToken } from '../src/lib/api.js';

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

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

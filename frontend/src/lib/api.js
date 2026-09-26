// Единственная точка обращения к серверу: токен входа, JSON и разбор единого формата ошибок
// {"error": {"code", "message", "details"}}. Компоненты получают данные только отсюда.
// Каждый ответ с полем server_now обновляет смещение часов, по которому считается таймер.

import { clockOffset } from './timer.js';

const TOKEN_KEY = 'provodnik.token';

let serverOffsetMs = 0;

class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details || {};
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
  window.dispatchEvent(new Event('provodnik-auth-change'));
}

export function subscribeToken(listener) {
  window.addEventListener('provodnik-auth-change', listener);
  window.addEventListener('storage', listener);
  return () => {
    window.removeEventListener('provodnik-auth-change', listener);
    window.removeEventListener('storage', listener);
  };
}

export function getServerOffset() {
  return serverOffsetMs;
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function rememberServerTime(data) {
  if (data && typeof data.server_now === 'string') {
    serverOffsetMs = clockOffset(data.server_now, Date.now());
  }
}

async function request(method, path, body, extraHeaders = {}) {
  const headers = { Accept: 'application/json', ...extraHeaders };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const init = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  let text;
  try {
    response = await fetch(path, init);
    text = await response.text();
  } catch {
    throw new ApiError(0, 'network', 'Сервер недоступен, попробуйте ещё раз через минуту');
  }
  const data = text ? parseJson(text) : null;
  if (!response.ok) {
    const error = (data && data.error) || {};
    const message = error.message || `Сервер ответил ошибкой ${response.status}`;
    // просроченный или отозванный токен бесполезен: убираем его, чтобы экраны отправили на вход
    if (response.status === 401 && token && getToken() === token && String(error.code).startsWith('token_')) {
      setToken(null);
    }
    throw new ApiError(response.status, error.code || 'http_error', message, error.details);
  }
  rememberServerTime(data);
  return data;
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}, headers) => request('POST', path, body, headers),
};

// Ключ идемпотентности старта живёт, пока экран не ушёл с места: повтор после сетевой ошибки
// или второй клик по той же кнопке вернёт то же прохождение, а не прервёт первое.
export function newIdempotencyKey() {
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function startSession(scenarioId, serviceClass, key) {
  const body = { scenario_id: scenarioId };
  if (serviceClass) {
    body.service_class = serviceClass;
  }
  return api.post('/api/sessions', body, { 'Idempotency-Key': key });
}

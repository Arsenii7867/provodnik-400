// Единственная точка обращения к серверу: токен входа, JSON и разбор единого формата ошибок
// {"error": {"code", "message", "details"}}. Компоненты получают данные только отсюда.

const TOKEN_KEY = 'provodnik.token';

export class ApiError extends Error {
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
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
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
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, 'network', 'Сервер недоступен, попробуйте ещё раз через минуту');
  }
  const text = await response.text();
  const data = text ? parseJson(text) : null;
  if (!response.ok) {
    const error = (data && data.error) || {};
    const message = error.message || `Сервер ответил ошибкой ${response.status}`;
    throw new ApiError(response.status, error.code || 'http_error', message, error.details);
  }
  return data;
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}, headers) => request('POST', path, body, headers),
};

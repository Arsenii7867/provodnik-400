"""Лимит попыток входа: скользящее окно в памяти по ключу (адрес клиента и код сотрудника).
Попытка резервирует слот до проверки PIN и освобождает его при удачном входе, поэтому
одновременные запросы не проскакивают между проверкой и записью неудачи, а зрители демо за одним
адресом не мешают друг другу удачными входами. Сервер работает одним процессом, поэтому память,
а не таблица."""

import logging
import math
import threading
from collections import deque
from datetime import timedelta

from app.errors import ApiError

logger = logging.getLogger("provodnik")
WINDOW = timedelta(minutes=1)
_attempts = {}
_lock = threading.Lock()


def check(key: str, now, limit: int):
    """Резервирует попытку и возвращает её метку; при заполненном окне 429 с Retry-After."""
    with _lock:
        attempts = _trim(key, now)
        if len(attempts) < limit:
            attempts.append(now)
            return now
        retry_after = max(1, math.ceil((attempts[0] + WINDOW - now).total_seconds()))
    logger.warning("лимит входа исчерпан: ключ %r", key)
    raise ApiError(
        429,
        "rate_limited",
        "Слишком много неудачных попыток входа, подождите минуту",
        {"retry_after": retry_after},
        {"Retry-After": str(retry_after)},
    )


def release(key: str, ticket):
    with _lock:
        attempts = _attempts.get(key)
        if attempts and ticket in attempts:
            attempts.remove(ticket)
        if not attempts:
            _attempts.pop(key, None)


def _trim(key, now):
    attempts = _attempts.setdefault(key, deque())
    while attempts and attempts[0] <= now - WINDOW:
        attempts.popleft()
    return attempts


def reset():
    with _lock:
        _attempts.clear()

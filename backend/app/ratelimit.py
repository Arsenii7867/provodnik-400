"""Лимит попыток входа: скользящее окно в памяти по адресу клиента. Считаются только неудачные
попытки, чтобы зрители демо за одним адресом не мешали друг другу удачными входами; при
превышении 429 с Retry-After. Сервер работает одним процессом, поэтому память, а не таблица."""

import math
import threading
from collections import deque
from datetime import timedelta

from app.errors import ApiError

WINDOW = timedelta(minutes=1)
_failures = {}
_lock = threading.Lock()


def check(key: str, now, limit: int):
    with _lock:
        attempts = _trim(key, now)
        if len(attempts) < limit:
            return
        retry_after = max(1, math.ceil((attempts[0] + WINDOW - now).total_seconds()))
    raise ApiError(
        429,
        "rate_limited",
        "Слишком много неудачных попыток входа, подождите минуту",
        {"retry_after": retry_after},
        {"Retry-After": str(retry_after)},
    )


def register_failure(key: str, now):
    with _lock:
        _trim(key, now).append(now)


def _trim(key, now):
    attempts = _failures.setdefault(key, deque())
    while attempts and attempts[0] <= now - WINDOW:
        attempts.popleft()
    return attempts


def reset():
    with _lock:
        _failures.clear()

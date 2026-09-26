"""Единственная точка времени сервера: aware datetime в UTC. Тесты сдвигают часы через travel
и freeze, поэтому истечение таймера проверяется без ожидания и без моков; сервисы получают
now() аргументом, а не спрашивают время сами."""

from datetime import UTC, datetime, timedelta

_offset = timedelta()
_frozen = None


def now():
    if _frozen is not None:
        return _frozen
    return datetime.now(UTC) + _offset


def travel(seconds):
    """Сдвигает часы для всех последующих вызовов; отрицательное значение возвращает назад."""
    global _offset, _frozen
    if _frozen is not None:
        _frozen = _frozen + timedelta(seconds=seconds)
    else:
        _offset = _offset + timedelta(seconds=seconds)


def freeze(moment):
    global _frozen
    _frozen = moment


def reset():
    global _offset, _frozen
    _offset = timedelta()
    _frozen = None

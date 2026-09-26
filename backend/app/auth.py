"""Вход по коду сотрудника и PIN, токены и зависимости доступа. PIN хранится как pbkdf2 с солью,
токен в базе только как sha256: утечка таблицы не даёт ни PIN, ни рабочих токенов."""

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select

from app import clock
from app.db import Db
from app.errors import ApiError
from app.models import AuthToken, Employee

PBKDF2_ROUNDS = 100_000
DUMMY_SALT = "no-such-employee"
bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS).hex()


def verify_pin(employee: Employee, pin: str) -> bool:
    return hmac.compare_digest(hash_pin(pin, employee.pin_salt), employee.pin_hash)


def verify_login(employee: Employee | None, pin: str) -> bool:
    """Неизвестный код проверяется столько же, сколько неверный PIN: по времени ответа код не угадать."""
    if employee is None:
        hash_pin(pin, DUMMY_SALT)
        return False
    return verify_pin(employee, pin)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(db, employee: Employee, now, ttl_hours: int):
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=ttl_hours)
    hashed = token_hash(token)
    db.add(AuthToken(token_hash=hashed, employee_id=employee.id, expires_at=expires_at, created_at=now))
    return token, expires_at


def revoke_token(db, token: str):
    db.execute(delete(AuthToken).where(AuthToken.token_hash == token_hash(token)))


def employee_view(employee: Employee) -> dict:
    return {
        "employee_code": employee.code,
        "display_name": employee.display_name,
        "role": employee.role,
        "brigade": employee.brigade.name,
        "depot": employee.brigade.depot.name,
    }


def current_employee(credentials: Credentials, db: Db) -> Employee:
    if credentials is None:
        raise ApiError(401, "token_missing", "Нужен вход: передайте токен в заголовке Authorization")
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == token_hash(credentials.credentials)))
    if row is None:
        raise ApiError(401, "token_invalid", "Токен не найден: войдите заново")
    if row.expires_at <= clock.now():
        raise ApiError(401, "token_expired", "Срок токена истёк: войдите заново")
    return db.get(Employee, row.employee_id)


CurrentEmployee = Annotated[Employee, Depends(current_employee)]


def require_role(role: str):
    def check(employee: CurrentEmployee) -> Employee:
        if employee.role != role:
            raise ApiError(403, "role_required", f"Это действие доступно только роли {role}")
        return employee

    return check


def require_api_key(request: Request, x_api_key: Annotated[str | None, Header()] = None):
    """Доступ HR и LMS по заголовку X-API-Key; сравнение за постоянное время."""
    if not x_api_key:
        raise ApiError(401, "api_key_required", "Нужен заголовок X-API-Key")
    if not hmac.compare_digest(x_api_key, request.app.state.settings.integration_api_key):
        raise ApiError(401, "api_key_invalid", "Ключ интеграции не подходит")

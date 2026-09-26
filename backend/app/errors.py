"""Единый формат ошибок API: тело всегда {"error": {"code", "message", "details"}}.
Здесь же реестр кодов, которыми пользуются остальные модули; клиент показывает message
и ветвится по code, стек исключения наружу не уходит никогда."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("provodnik")

# коды для HTTPException без собственного кода: их поднимает сам фреймворк (нет маршрута, метод не тот)
CODES_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
}
# текст фреймворка (Not Found, Method Not Allowed) наружу не уходит: клиент видит русскую фразу по статусу
MESSAGES_BY_STATUS = {
    400: "Запрос не удалось разобрать",
    401: "Нужен вход",
    403: "Доступ запрещён",
    404: "Такого адреса нет",
    405: "Метод для этого адреса не поддерживается",
    409: "Конфликт состояния",
    413: "Тело запроса больше допустимого",
    422: "Запрос не прошёл проверку",
    429: "Слишком много запросов",
    500: "Внутренняя ошибка сервера",
}


class ApiError(Exception):
    """Ошибка предметной области с HTTP-статусом и машинным кодом для клиента."""

    def __init__(self, status: int, code: str, message: str, details=None, headers=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def error_response(status: int, code: str, message: str, details=None, headers=None):
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(status_code=status, content=body, headers=headers or None)


async def handle_api_error(request: Request, exc: ApiError):
    return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)


async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    code = CODES_BY_STATUS.get(exc.status_code, "http_error")
    message = MESSAGES_BY_STATUS.get(exc.status_code, "Запрос отклонён")
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def handle_validation_error(request: Request, exc: RequestValidationError):
    # ошибки Pydantic отдаём списком, чтобы клиент мог подсветить поле; текст общий и по-русски
    details = {"errors": [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]}
    return error_response(422, "validation_error", "Тело или параметры запроса не прошли проверку", details)


async def handle_unexpected(request: Request, exc: Exception):
    logger.exception("необработанная ошибка на %s %s", request.method, request.url.path)
    return error_response(500, "internal_error", "Внутренняя ошибка сервера")


def install_error_handlers(app: FastAPI):
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected)

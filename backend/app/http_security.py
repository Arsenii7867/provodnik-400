"""Заголовки безопасности и ограничение тела до разбора JSON и побочных эффектов API."""

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import MESSAGES_BY_STATUS, error_response

MAX_BODY_BYTES = 1_000_000
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class SecurityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if scope["path"].startswith("/api"):
                    # Ответы API персональные: браузер и прокси их не кэшируют.
                    headers["Cache-Control"] = "no-store"
            await send(message)

        async def reject():
            response = error_response(413, "payload_too_large", MESSAGES_BY_STATUS[413])
            await response(scope, receive, secure_send)

        length = Headers(scope=scope).get("content-length", "").lstrip("0") or "0"
        limit = str(MAX_BODY_BYTES)
        # Сравнение строк не преобразует недоверенное число из тысяч цифр в int.
        if length.isascii() and length.isdigit():
            if len(length) > len(limit) or (len(length) == len(limit) and length > limit):
                await reject()
                return

        # Ограниченный буфер нужен до вызова API: превышение не должно оставлять
        # изменений в базе даже у маршрута, который сам тело не читает.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                await reject()
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_body():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, secure_send)

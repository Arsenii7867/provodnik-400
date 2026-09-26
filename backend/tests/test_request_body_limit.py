"""Лимит проверяет реальные ASGI-чанки до разбора JSON и вызова обработчика."""

import asyncio

import httpx
import pytest
from fastapi import Request, Response

from app.http_security import MAX_BODY_BYTES


def streamed_request(app, chunks, headers=None):
    consumed = []
    handled = []

    @app.post("/api/probe/body", include_in_schema=False)
    async def echo(request: Request):
        handled.append(True)
        return Response(await request.body(), media_type="application/octet-stream")

    async def run():
        async def stream():
            for chunk in chunks:
                consumed.append(len(chunk))
                yield chunk

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            return await client.post("/api/probe/body", content=stream(), headers=headers)

    return asyncio.run(run()), consumed, handled


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "0"}, {"Content-Length": "1"}])
def test_stream_over_limit_is_rejected_before_handler(app, headers):
    response, consumed, handled = streamed_request(
        app, [b"a" * MAX_BODY_BYTES, b"b", b"must not be read"], headers
    )
    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "payload_too_large",
            "message": "Тело запроса больше допустимого",
            "details": {},
        }
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert consumed == [MAX_BODY_BYTES, 1]
    assert not handled


@pytest.mark.parametrize("size", [0, MAX_BODY_BYTES - 1, MAX_BODY_BYTES])
def test_stream_within_limit_reaches_handler_unchanged(app, size):
    body = (b"0123456789" * (size // 10 + 1))[:size]
    response, _, handled = streamed_request(app, [body[:7], b"", body[7:]])
    assert response.status_code == 200
    assert response.content == body
    assert handled == [True]


@pytest.mark.parametrize("length", [str(MAX_BODY_BYTES + 1), "9" * 5000], ids=["over", "huge-integer"])
def test_declared_oversize_is_rejected_without_reading_body(app, length):
    response, consumed, handled = streamed_request(app, [b"unused"], {"Content-Length": length})
    assert response.status_code == 413
    assert not consumed
    assert not handled


def test_disconnect_during_upload_does_not_call_handler_or_send_response(app):
    handled = []
    sent = []
    messages = iter(
        [
            {"type": "http.request", "body": b"unfinished", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    @app.post("/api/probe/disconnect", include_in_schema=False)
    async def handler():
        handled.append(True)
        return {"ok": True}

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    asyncio.run(
        app(
            {"type": "http", "method": "POST", "path": "/api/probe/disconnect", "headers": []},
            receive,
            send,
        )
    )
    assert not handled
    assert not sent

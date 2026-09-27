"""Одна политика заголовков для обычных ответов и внешнего обработчика ошибок 500."""

from starlette.datastructures import MutableHeaders

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def apply_security_headers(headers: MutableHeaders, path: str) -> None:
    for name, value in SECURITY_HEADERS.items():
        headers.setdefault(name, value)
    if path.startswith("/api"):
        # Ответы API персональные: браузер и прокси их не кэшируют.
        headers["Cache-Control"] = "no-store"

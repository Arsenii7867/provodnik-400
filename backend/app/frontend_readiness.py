"""Готовность смонтированного SPA и локальных JS/CSS, указанных в его index.html."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src"):
            self.urls.append(attributes["src"])
        if tag == "link" and "stylesheet" in (attributes.get("rel") or "").lower().split():
            if attributes.get("href"):
                self.urls.append(attributes["href"])


def frontend_ready(dist: Path, mounted: bool) -> bool:
    if not mounted:
        return False
    try:
        parser = AssetParser()
        parser.feed((dist / "index.html").read_text(encoding="utf-8"))
        root = dist.resolve()
        for url in parser.urls:
            reference = urlsplit(url)
            if reference.scheme or reference.netloc:
                continue  # Внешние ресурсы эта локальная проверка не опрашивает.
            asset = (root / unquote(reference.path).lstrip("/")).resolve()
            if root not in asset.parents or not asset.is_file():
                return False
        return True
    except (OSError, UnicodeError, ValueError):
        return False

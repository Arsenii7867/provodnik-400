"""Контент в памяти сервера с перечитыванием по изменению файлов. При каждом обращении
сравниваются mtime и размер YAML в папке content; изменения проходят через валидатор. Пока в
папке есть хоть одна ошибка (нечитаемый файл, сломанный справочник, невалидный сценарий), сервер
работает на прежней проверенной версии целиком, а ошибки видны в store.errors и в логе. Так
развилку можно добавить в работающий сервер без перезапуска, а опечатка в YAML не роняет каталог."""

import logging
import threading
from pathlib import Path

from app.scenarios import validator
from app.scenarios.loader import REFERENCE_FILES, Content

logger = logging.getLogger("provodnik")


class ContentStore:
    def __init__(self, content_dir):
        self.content_dir = Path(content_dir)
        self.lock = threading.RLock()
        self.stamps = None
        self.reported_ids = None
        self.loaded = Content()
        self.analyses = {}
        self.sources = {}
        self.error_items = []
        self.errors = []
        self.summary = ""

    def content(self):
        self.refresh()
        return self.loaded

    def scenarios(self):
        return self.content().scenarios

    def scenario(self, scenario_id):
        return self.scenarios().get(scenario_id)

    def analysis(self, scenario_id):
        self.refresh()
        return self.analyses.get(scenario_id)

    def source_text(self, scenario_id):
        self.refresh()
        return self.sources.get(scenario_id, "")

    def watched_files(self):
        files = [self.content_dir / f"{name}.yaml" for name in REFERENCE_FILES]
        return files + sorted((self.content_dir / "scenarios").glob("*.yaml"))

    def file_stamps(self):
        stamps = {}
        for path in self.watched_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            stamps[path] = (stat.st_mtime_ns, stat.st_size)
        return stamps

    def refresh(self, force=False):
        with self.lock:
            stamps = self.file_stamps()
            if stamps == self.stamps and not force:
                return None
            try:
                report = self.read_all()
            except Exception:
                # сбой чтения не должен ронять каждый запрос: живёт прежний контент до следующей правки
                logger.exception("контент: не удалось перечитать %s", self.content_dir)
                self.record_errors(
                    [{"file": str(self.content_dir), "line": 0, "message": "сбой чтения, см. лог"}]
                )
                report = None
            self.stamps = stamps
            return report

    def reload(self):
        """Принудительное перечитывание с отчётом о том, что появилось и что пропало."""
        with self.lock:
            before = self.reported_ids or set()
            self.refresh(force=True)
            after = set(self.loaded.scenarios)
            self.reported_ids = after
            return {
                "loaded": sorted(after),
                "new": sorted(after - before),
                "removed": sorted(before - after),
                "errors": list(self.error_items),
                "summary": self.summary,
            }

    def read_all(self):
        content, report = validator.load_validated(self.content_dir)
        errors = collect_errors(self.content_dir, content, report)
        if errors and self.stamps is not None:
            # частично обновлять нельзя: сценарий прежней версии может ссылаться на класс или норму, которых
            # в новых справочниках уже нет, поэтому до исправления ошибок живёт вся прежняя версия
            logger.error("контент: сервер работает на прежней версии, пока ошибки не исправлены")
        else:
            self.loaded = content
            # Автообновление каталога не должно поглощать новые сценарии до рассылки.
            if self.reported_ids is None:
                self.reported_ids = set(content.scenarios)
            valid = {key: entry for key, entry in report["scenarios"].items() if entry["valid"]}
            self.analyses = {key: entry["analysis"] for key, entry in valid.items()}
            self.sources = {key: read_text(entry["file"]) for key, entry in valid.items()}
        self.record_errors(errors)
        self.summary = report["summary"]
        return report

    def record_errors(self, errors):
        self.error_items = errors
        self.errors = [f"{item['file']}:{item['line']}: {item['message']}" for item in errors]
        for line in self.errors:
            logger.error("контент: %s", line)


def collect_errors(content_dir, content, report):
    """Все ошибки папки content одним списком {file, line, message}: нечитаемые файлы, сломанные
    справочники и ошибки валидатора у невалидных сценариев."""
    errors = list(content.errors)
    for problem in report["reference_problems"]:
        errors.append({"file": str(content_dir), "line": 0, "message": problem})
    for scenario_id in report["invalid"]:
        entry = report["scenarios"][scenario_id]
        for finding in entry["findings"]:
            if finding.severity == "error":
                message = f"{finding.code}: {finding.message}"
                errors.append({"file": str(entry["file"]), "line": finding.line, "message": message})
    return errors


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""

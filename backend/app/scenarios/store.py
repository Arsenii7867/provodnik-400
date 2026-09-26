"""Контент в памяти сервера с перечитыванием по изменению файлов. При каждом обращении
сравниваются mtime и размер YAML в папке content; изменения проходят через валидатор, сломанный
файл оставляет предыдущую версию сценария и попадает в store.errors и в лог. Так развилку можно
добавить в работающий сервер без перезапуска, а опечатка в YAML не роняет каталог."""

import logging
import threading
from pathlib import Path

from app.scenarios import validator
from app.scenarios.loader import REFERENCE_FILES, Content

logger = logging.getLogger("provodnik")


class ContentStore:
    def __init__(self, content_dir):
        self.content_dir = Path(content_dir)
        self.lock = threading.Lock()
        self.stamps = None
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
            report = self.read_all()
            self.stamps = stamps
            return report

    def reload(self):
        """Принудительное перечитывание с отчётом о том, что появилось и что пропало."""
        before = set(self.loaded.scenarios)
        self.refresh(force=True)
        after = set(self.loaded.scenarios)
        return {
            "loaded": sorted(after),
            "new": sorted(after - before),
            "removed": sorted(before - after),
            "errors": list(self.error_items),
            "summary": self.summary,
        }

    def read_all(self):
        content, report = validator.load_validated(self.content_dir)
        errors = list(content.errors)
        for problem in report["reference_problems"]:
            errors.append({"file": str(self.content_dir), "line": 0, "message": problem})
        for scenario_id in report["invalid"]:
            entry = report["scenarios"][scenario_id]
            for finding in entry["findings"]:
                if finding.severity == "error":
                    message = f"{finding.code}: {finding.message}"
                    errors.append({"file": str(entry["file"]), "line": finding.line, "message": message})
        if report["reference_problems"] and self.stamps is not None:
            # без целых справочников сценарии проверить нельзя: остаётся прошлый контент целиком
            logger.error("контент: справочники сломаны, сервер работает на прежней версии")
        else:
            self.keep_previous_versions(content, report)
            self.loaded = content
        self.error_items = errors
        self.errors = [f"{item['file']}:{item['line']}: {item['message']}" for item in errors]
        self.summary = report["summary"]
        for line in self.errors:
            logger.error("контент: %s", line)
        return report

    def keep_previous_versions(self, content, report):
        """Сломанный сценарий не исчезает из каталога: остаётся версия, прошедшая проверку раньше."""
        broken = set(report["invalid"])
        for error in content.errors:
            broken.update(self.ids_by_file(error["file"]))
        analyses = {}
        sources = {}
        for scenario_id, entry in report["scenarios"].items():
            if entry["valid"]:
                analyses[scenario_id] = entry["analysis"]
                sources[scenario_id] = read_text(entry["file"])
        for scenario_id in broken:
            if scenario_id in self.loaded.scenarios and scenario_id not in content.scenarios:
                content.scenarios[scenario_id] = self.loaded.scenarios[scenario_id]
                content.files[scenario_id] = self.loaded.files[scenario_id]
                analyses[scenario_id] = self.analyses.get(scenario_id)
                sources[scenario_id] = self.sources.get(scenario_id, "")
        self.analyses = analyses
        self.sources = sources

    def ids_by_file(self, file):
        path = Path(file)
        return [scenario_id for scenario_id, known in self.loaded.files.items() if Path(known) == path]


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""

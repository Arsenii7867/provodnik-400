"""ContentStore перечитывает изменённые YAML по mtime, переживает сломанный файл и отчитывается
о новых сценариях при принудительной перезагрузке."""

import os
import shutil
from pathlib import Path

import pytest

from app.scenarios.store import ContentStore

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SCENARIO = "medical_chest_pain"


@pytest.fixture
def content_copy(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, target)
    return target


def touch_later(path, seconds=5):
    # mtime сдвигается явно: две записи подряд могут попасть в один тик файловой системы
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 10**9))


def test_store_reloads_changed_file(content_copy):
    store = ContentStore(content_copy)
    assert store.scenario(SCENARIO)["title"] == "Давит в груди"
    path = content_copy / "scenarios" / f"{SCENARIO}.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "title: Давит в груди", "title: Давит в груди. Версия 3", 1
    )
    path.write_text(text, encoding="utf-8")
    touch_later(path)
    assert store.scenario(SCENARIO)["title"] == "Давит в груди. Версия 3"
    assert store.errors == []
    assert store.analysis(SCENARIO)["own"]["paths"] > 0


def test_store_keeps_previous_on_broken_file(content_copy):
    store = ContentStore(content_copy)
    before = store.scenario(SCENARIO)
    path = content_copy / "scenarios" / f"{SCENARIO}.yaml"
    good = path.read_text(encoding="utf-8")
    path.write_text(good + "\nnodes: [обрыв", encoding="utf-8")
    touch_later(path)
    assert store.scenario(SCENARIO) == before
    assert len(store.errors) == 1 and store.errors[0].startswith(str(path))
    assert store.source_text(SCENARIO) == good
    path.write_text(good.replace("next: at_the_seat", "next: nowhere", 1), encoding="utf-8")
    touch_later(path, 10)
    assert store.scenario(SCENARIO) == before
    assert any("unknown_node" in line for line in store.errors)
    path.write_text(good, encoding="utf-8")
    touch_later(path, 15)
    assert store.scenario(SCENARIO) == before and store.errors == []


def test_store_keeps_everything_when_rules_broken(content_copy):
    store = ContentStore(content_copy)
    before = dict(store.scenarios())
    rules = content_copy / "rules.yaml"
    rules.write_text("scales: {min: 0}\n", encoding="utf-8")
    touch_later(rules)
    assert store.scenarios() == before
    assert store.content().rules["outcome"]["incident_if_safety_below"] == 40
    assert store.errors


def test_reload_report_lists_new_ids(content_copy):
    store = ContentStore(content_copy)
    assert list(store.scenarios()) == [SCENARIO]
    source = content_copy / "scenarios" / f"{SCENARIO}.yaml"
    copy = content_copy / "scenarios" / "medical_copy.yaml"
    text = source.read_text(encoding="utf-8").replace(f"id: {SCENARIO}", "id: medical_copy", 1)
    copy.write_text(text, encoding="utf-8")
    report = store.reload()
    assert report["new"] == ["medical_copy"] and report["removed"] == []
    assert report["loaded"] == [SCENARIO, "medical_copy"]
    assert report["summary"].startswith("ИТОГ: сценариев=2")
    copy.unlink()
    report = store.reload()
    assert report["removed"] == ["medical_copy"] and report["loaded"] == [SCENARIO]

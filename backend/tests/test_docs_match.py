"""Документация согласована с кодом: каждый путь OpenAPI описан в docs/api.md и наоборот,
сценарии, на которые ссылаются docs, существуют, у каждой диаграммы Mermaid есть отрендеренный
SVG и картинка вставлена в архитектуру, README называет команды запуска."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SCENARIOS_DIR = ROOT / "content" / "scenarios"
API_PATH = re.compile(r"(/api/[A-Za-z0-9_/{}\-]+)")
SCENARIO_FILE = re.compile(r"`([a-z][a-z0-9_]*)\.yaml`")
DOCUMENTS = (
    "README.md",
    "docs/architecture.md",
    "docs/api.md",
    "docs/user_flow.md",
    "docs/scenarios.md",
    "docs/security.md",
    "docs/roadmap.md",
)
README_COMMANDS = (
    "python -m venv",
    "pip install -r requirements.txt",
    "python -m app.seed",
    "uvicorn app.main:app",
    "npm ci",
    "npm run build",
)
MIN_LINES = 30
MIN_SVG_BYTES = 2000


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def generic(path):
    # /api/sessions/{run_id} и /api/sessions/{id} это один и тот же путь
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_api_md_matches_openapi(client):
    spec = client.get("/openapi.json").json()
    actual = {generic(path) for path in spec["paths"]}
    documented = {generic(path) for path in API_PATH.findall(read("docs/api.md"))}
    assert actual - documented == set(), "в docs/api.md не описаны пути"
    assert documented - actual == set(), "docs/api.md описывает пути, которых нет в OpenAPI"


def test_scenario_ids_in_docs_exist():
    ids = {path.stem for path in SCENARIOS_DIR.glob("*.yaml")}
    for name in ("docs/scenarios.md", "docs/user_flow.md"):
        mentioned = set(SCENARIO_FILE.findall(read(name)))
        assert mentioned, f"{name} не ссылается ни на один файл сценария"
        assert mentioned <= ids, f"{name} ссылается на сценарии, которых нет: {mentioned - ids}"


def test_mermaid_sources_rendered():
    sources = sorted((DOCS / "diagrams").glob("*.mmd"))
    architecture = read("docs/architecture.md")
    assert len(sources) >= 3
    for source in sources:
        svg = DOCS / "img" / f"{source.stem}.svg"
        assert svg.exists(), f"для {source.name} нет docs/img/{source.stem}.svg"
        assert svg.stat().st_size >= MIN_SVG_BYTES, f"{svg.name} пустой"
        assert "<svg" in svg.read_text(encoding="utf-8")[:2000]
        assert f"img/{source.stem}.svg" in architecture, f"{svg.name} не вставлен в docs/architecture.md"


def test_documents_exist_and_are_not_stubs():
    for name in DOCUMENTS:
        text = read(name)
        assert text.count("\n") >= MIN_LINES, f"{name} короче {MIN_LINES} строк"
        # длинное и короткое тире в русских документах не используются
        assert chr(0x2014) not in text and chr(0x2013) not in text, f"в {name} есть тире"


def test_readme_names_launch_commands():
    readme = read("README.md")
    for command in README_COMMANDS:
        assert command in readme, f"в README нет команды «{command}»"

"""Граф сценария: узлы и рёбра, ребро истечения у каждого таймера, поиск циклов, Mermaid и
фрагмент YAML стартового узла."""

from pathlib import Path

import pytest

from app.scenarios import analysis, graph
from app.scenarios.loader import load_content

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture(scope="module")
def content():
    return load_content(CONTENT_DIR)


@pytest.fixture(scope="module")
def built(content):
    scenario = content.scenarios["medical_chest_pain"]
    source = content.files["medical_chest_pain"].read_text(encoding="utf-8")
    return graph.build_graph(scenario, analysis.analyze(scenario, content), source)


def test_graph_nodes_and_expire_edges(built, content):
    scenario = content.scenarios["medical_chest_pain"]
    assert len(built["nodes"]) == len(scenario["nodes"]) == 12
    expire_edges = [edge for edge in built["edges"] if edge["kind"] == "expire"]
    assert {edge["from"] for edge in expire_edges} == {"intro", "help_options", "medic_found"}
    for edge in expire_edges:
        incoming = [item for item in built["edges"] if item["to"] == edge["to"]]
        assert incoming == [edge]
    conditional = [edge for edge in built["edges"] if edge["conditional"]]
    assert {edge["option_id"] for edge in conditional} >= {"pa_medic", "hide_pill", "tell_about_pill"}
    by_id = {node["id"]: node for node in built["nodes"]}
    assert by_id["intro"]["depth"] == 0
    assert by_id["intro"]["timer_seconds"] == 20
    assert by_id["ending_station_medics"]["type"] == "ending"
    assert by_id["ending_station_medics"]["label"] == "Скорая у вагона"
    assert built["paths"] == 411
    assert built["scale_ranges"]["safety"]["min"] == 0


def test_mermaid_export(built):
    lines = built["mermaid"].splitlines()
    assert lines[0] == "flowchart TD"
    assert any(line.strip().startswith("intro -.->|истечение| collapsed") for line in lines)
    assert any("-->|pa_medic (условие)|" in line for line in lines)
    assert any('ending_incident_pills[["' in line for line in lines)


def test_yaml_excerpt_shows_start_node(built):
    excerpt = built["yaml_excerpt"].splitlines()
    assert excerpt[0] == "  intro:"
    assert any("seconds: 20" in line for line in excerpt)
    assert len(excerpt) <= graph.EXCERPT_LINES


def test_find_cycle_and_reachability():
    scenario = {
        "start": {"node": "a"},
        "nodes": {
            "a": {"type": "dialog", "options": [{"id": "go", "next": "b"}]},
            "b": {"type": "event", "next": "a"},
            "c": {"type": "ending"},
        },
    }
    edges = graph.edges_of(scenario)
    assert graph.find_cycle(scenario, edges) == ["a", "b", "a"]
    assert graph.reachable_nodes(scenario, edges) == {"a": 0, "b": 1}
    scenario["nodes"]["b"]["next"] = "c"
    assert graph.find_cycle(scenario, graph.edges_of(scenario)) == []

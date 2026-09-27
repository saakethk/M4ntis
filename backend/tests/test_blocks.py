"""Canvas validation, macro expansion, and compiling documents that use macro blocks."""

from __future__ import annotations

import pytest

from backend.mantis.blocks.canvas import CanvasError, normalize_graph
from backend.mantis.blocks.catalog import BLOCKS, catalog_for_prompt
from backend.mantis.blocks.document import document_from_canvas
from backend.mantis.blocks.macros import expand_document, source_node
from backend.mantis.services.compiler import CompilationFailed, compile_document

BANDS = {
    "nodes": [
        {"id": "start", "type": "start", "params": {"resolution": "15m"}},
        {"id": "t0", "type": "get_ticker", "params": {"symbol": "nvda"}},
        {"id": "bands", "type": "mean_reversion_bands", "params": {"n": 20, "k": 2}},
        {"id": "low", "type": "if", "params": {"operator": "<="}},
        {"id": "buy", "type": "buy", "params": {"quantity": 5}},
    ],
    "edges": [
        {"source": "start", "sourceHandle": "exec:out", "target": "low", "targetHandle": "exec:in"},
        {"source": "bands", "sourceHandle": "data:lower", "target": "low", "targetHandle": "data:a"},
        {"from": "t0", "sourceHandle": "data:out", "to": "low", "targetHandle": "data:b"},
        {"source": "low", "sourceHandle": "exec:then", "target": "buy", "targetHandle": "exec:in"},
    ],
}


def z_score_graph(operator: str = "<") -> dict:
    return normalize_graph(
        {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "t0", "type": "get_ticker", "params": {"symbol": "AAPL"}},
                {"id": "z", "type": "z_score", "params": {"n": 20}},
                {"id": "floor", "type": "constant", "params": {"value": -2}},
                {"id": "cheap", "type": "if", "params": {"operator": operator}},
                {"id": "buy", "type": "buy"},
            ],
            "edges": [
                {"source": "start", "sourceHandle": "exec:out", "target": "cheap", "targetHandle": "exec:in"},
                {"source": "z", "sourceHandle": "data:out", "target": "cheap", "targetHandle": "data:a"},
                {"source": "floor", "sourceHandle": "data:out", "target": "cheap", "targetHandle": "data:b"},
                {"source": "cheap", "sourceHandle": "exec:then", "target": "buy", "targetHandle": "exec:in"},
            ],
        }
    )


def test_normalize_fills_defaults_and_uppercases_tickers():
    graph = normalize_graph(BANDS)
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["t0"]["params"]["symbol"] == "NVDA"
    assert by_id["buy"]["params"] == {"buffer": 0, "quantity": 5}
    assert graph["edges"][2]["source"] == "t0"


def test_start_is_added_when_missing():
    graph = normalize_graph({"nodes": [{"id": "c", "type": "constant"}], "edges": []})
    assert graph["nodes"][0]["id"] == "start"


@pytest.mark.parametrize(
    "graph, message",
    [
        ({"nodes": [{"id": "a", "type": "log2"}], "edges": []}, "unknown block"),
        ({"nodes": [{"id": "a", "type": "sma", "params": {"n": 99}}], "edges": []}, "from 1 to 30"),
        ({"nodes": [{"id": "a", "type": "sma", "params": {"size": 3}}], "edges": []}, "no param"),
        (
            {
                "nodes": [{"id": "a", "type": "set_var"}, {"id": "b", "type": "set_var"}],
                "edges": [
                    {"source": "a", "sourceHandle": "exec:out", "target": "b", "targetHandle": "exec:in"},
                    {"source": "b", "sourceHandle": "exec:out", "target": "a", "targetHandle": "exec:in"},
                ],
            },
            "cycle",
        ),
        (
            {
                "nodes": [{"id": "c", "type": "constant"}, {"id": "i", "type": "if"}],
                "edges": [{"source": "c", "sourceHandle": "data:out", "target": "i", "targetHandle": "exec:in"}],
            },
            "exec ports only",
        ),
    ],
)
def test_invalid_graphs_are_rejected(graph, message):
    with pytest.raises(CanvasError, match=message):
        normalize_graph(graph)


def test_catalog_prompt_lists_every_block():
    text = catalog_for_prompt()
    assert all(f"- {name} (" in text for name in BLOCKS)


def test_z_score_expands_into_compiler_blocks():
    expanded = expand_document(document_from_canvas(z_score_graph()))
    types = {n["id"]: n["type"] for n in expanded["flow"]["nodes"]}
    assert "z" not in types
    assert types["z::price"] == "current_price" and types["z::ratio"] == "divide"
    rewired = next(e for e in expanded["flow"]["edges"] if e["target"] == "cheap" and e["targetHandle"] == "data:a")
    assert (rewired["source"], rewired["sourceHandle"]) == ("z::ratio", "data:out")


def test_z_score_strategy_compiles():
    result = compile_document(document_from_canvas(z_score_graph()))
    assert result["ok"] is True
    assert result["manifest"]["words"]


def test_get_balance_strategy_normalizes_and_compiles():
    graph = normalize_graph(
        {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "t0", "type": "get_ticker", "params": {"symbol": "AAPL"}},
                {"id": "bal", "type": "get_balance"},
                {"id": "floor", "type": "constant", "params": {"value": 500}},
                {"id": "ok", "type": "if", "params": {"operator": ">"}},
                {"id": "buy", "type": "buy", "params": {"quantity": 1}},
            ],
            "edges": [
                {"source": "start", "sourceHandle": "exec:out", "target": "ok", "targetHandle": "exec:in"},
                {"source": "bal", "sourceHandle": "data:out", "target": "ok", "targetHandle": "data:a"},
                {"source": "floor", "sourceHandle": "data:out", "target": "ok", "targetHandle": "data:b"},
                {"source": "ok", "sourceHandle": "exec:then", "target": "buy", "targetHandle": "exec:in"},
            ],
        }
    )
    assert any(n["type"] == "get_balance" for n in graph["nodes"])
    result = compile_document(document_from_canvas(graph))
    assert result["ok"] is True
    assert "GETBALANCE" in result["asm"]


def test_diagnostics_on_generated_nodes_point_at_the_macro_block():
    graph = z_score_graph()
    for node in graph["nodes"]:
        if node["id"] == "z":
            node["params"]["buffer"] = 3
    with pytest.raises(CompilationFailed) as caught:
        compile_document(document_from_canvas(graph))
    nodes = {d.get("node") for d in caught.value.diagnostics}
    assert not any(n and "::" in n for n in nodes)
    assert source_node("z::sma") == "z"

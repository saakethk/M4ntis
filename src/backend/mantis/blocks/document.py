"""Convert between canvas graphs and ``m4ntis.strategy/v1`` documents.

The editor saves full documents (positions, viewport). The assistant works with
compact canvas graphs. :func:`document_from_canvas` builds the smallest document
the compiler accepts, so the agent can check a graph it is still editing.
"""

from __future__ import annotations

from typing import Any

DOCUMENT_SCHEMA = "m4ntis.strategy/v1"


def document_from_canvas(graph: dict[str, list], name: str = "Assistant draft") -> dict[str, Any]:
    return {
        "schema": DOCUMENT_SCHEMA,
        "name": name,
        "flow": {
            "nodes": [
                {"id": n["id"], "type": n["type"], "position": {"x": 0, "y": 0}, "data": {"params": dict(n["params"])}}
                for n in graph["nodes"]
            ],
            "edges": [
                {**edge, "id": f"e{index}", "data": {"kind": edge["sourceHandle"].split(":")[0]}}
                for index, edge in enumerate(graph["edges"])
            ],
        },
    }

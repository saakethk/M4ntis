"""The agent harness with a scripted model: tool loop, validation, fallbacks, and extension."""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from mantis.ai.agent import BLOCK_TOOLS, AgentHarness, Tool, ToolError, Workspace
from mantis.ai.assistant import system_prompt
from mantis.ai.providers import ChatResponse
from mantis.blocks.canvas import empty_canvas
from mantis.services import auth
from mantis.services.compiler import check_document


def scripted(*turns: object):
    """A fake model that answers with each turn in order and records what it was sent."""
    queue: Iterator[object] = iter(turns)
    seen: list[list] = []

    def complete(system: str, messages: list) -> str:
        seen.append(list(messages))
        turn = next(queue)
        return turn if isinstance(turn, str) else json.dumps(turn)

    return complete, seen


def call(name: str, **args: object) -> dict:
    return {"name": name, "args": args}


BUILD_CROSSOVER = {
    "tool_calls": [
        call("add_block", type="get_ticker", id="t0", params={"symbol": "msft"}),
        call("add_block", type="sma", id="fast", params={"n": 10}),
        call("add_block", type="sma", id="slow", params={"n": 30}),
        call("add_block", type="if", id="cross"),
        call("add_block", type="buy", id="buy"),
        call("connect", source="start", source_port="out", target="cross", target_port="in"),
        call("connect", source="fast", source_port="data:out", target="cross", target_port="a"),
        call("connect", source="slow", source_port="out", target="cross", target_port="b"),
        call("connect", source="cross", source_port="then", target="buy", target_port="exec:in"),
    ]
}


def test_agent_builds_checks_and_replies():
    complete, seen = scripted(BUILD_CROSSOVER, {"tool_calls": [call("check_strategy")]}, {"reply": "Built an SMA crossover."})
    result = AgentHarness(complete, "system", checker=check_document).run("build a crossover", empty_canvas())
    assert result.reply == "Built an SMA crossover."
    assert {n["id"] for n in result.graph["nodes"]} == {"start", "t0", "fast", "slow", "cross", "buy"}
    assert all(step.ok for step in result.steps)
    check_result = json.loads(seen[2][-1].content.split("\n", 1)[1])[0]["result"]
    assert check_result["compiles"] is True
    assert "Current canvas:" in seen[0][0].content


def test_failed_tool_calls_are_reported_and_leave_the_canvas_unchanged():
    complete, seen = scripted(
        {"tool_calls": [call("add_block", type="sma", params={"n": 500}), call("remove_block", id="start")]},
        {"reply": "Could not do that."},
    )
    result = AgentHarness(complete, "system").run("make a huge sma", empty_canvas())
    assert result.graph is None
    assert [step.ok for step in result.steps] == [False, False]
    errors = json.loads(seen[1][-1].content.split("\n", 1)[1])
    assert "from 1 to 30" in errors[0]["error"] and "cannot be removed" in errors[1]["error"]


def test_plain_text_is_the_reply_and_a_fenced_graph_is_applied():
    graph = {"nodes": [{"id": "start", "type": "start"}, {"id": "c", "type": "constant", "params": {"value": 3}}], "edges": []}
    complete, _ = scripted(f"Added a constant.\n```json\n{json.dumps({'graph': graph})}\n```")
    result = AgentHarness(complete, "system").run("add a constant", empty_canvas())
    assert result.reply == "Added a constant."
    assert [n["id"] for n in result.graph["nodes"]] == ["start", "c"]


def test_step_budget_is_enforced():
    complete, _ = scripted(*[{"tool_calls": [call("view_canvas")]}] * 3)
    result = AgentHarness(complete, "system", max_steps=3).run("loop", empty_canvas())
    assert "maximum number of steps" in result.reply and len(result.steps) == 3


def test_registries_are_extensible_without_touching_the_harness():
    counter = Tool("count_blocks", "Number of blocks on the canvas.", lambda ctx, _: len(ctx.workspace.graph["nodes"]))
    tools = BLOCK_TOOLS.extended(counter)
    complete, seen = scripted({"tool_calls": [call("count_blocks")]}, {"reply": "One block."})
    AgentHarness(complete, "system", tools=tools).run("how many?", empty_canvas())
    assert '"result":1' in seen[1][-1].content
    assert "count_blocks" not in BLOCK_TOOLS.names()
    with pytest.raises(ValueError):
        tools.register(counter)


def test_connect_replaces_the_existing_wire_on_a_data_input():
    ws = Workspace(empty_canvas())
    for node_id in ("a", "b"):
        ws.add_block("constant", node_id)
    ws.add_block("sqrt", "root")
    ws.connect("a", "out", "root", "x")
    ws.connect("b", "out", "root", "x")
    assert [(e["source"], e["target"]) for e in ws.graph["edges"]] == [("b", "root")]
    with pytest.raises(ToolError, match="input ports are"):
        ws.connect("a", "out", "root", "y")


def test_system_prompt_lists_tools_and_blocks():
    prompt = system_prompt()
    assert "check_strategy" in prompt and "z_score" in prompt and "{tools}" not in prompt


class FakeClient:
    model = "muse-spark-1.3"

    def __init__(self, *turns: str):
        self.turns = list(turns)
        self.calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), **kwargs})
        return ChatResponse(text=self.turns.pop(0), provider="meta", model=self.model)


@pytest.fixture
def signed_in():
    with patch.object(auth, "user_from_token", return_value=auth.User(4, "a@b.com")):
        yield


def test_llm_route_runs_the_agent_with_the_chosen_model(client, signed_in):
    fake = FakeClient(json.dumps(BUILD_CROSSOVER), json.dumps({"reply": "Done."}))
    with patch("mantis.ai.assistant.ChatClient.from_env", return_value=fake) as from_env:
        response = client.post(
            "/llm",
            json={
                "prompt": "build a crossover",
                "provider": "meta",
                "model": "muse-spark-1.3",
                "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}],
                "graph": {"nodes": [{"id": "start", "type": "start", "position": {"x": 0, "y": 0}, "data": {"params": {"resolution": "15m"}}}], "edges": []},
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    from_env.assert_called_once_with("meta", "muse-spark-1.3")
    assert body["reply"] == "Done." and body["model"] == "muse-spark-1.3"
    assert len(body["steps"]) == 9 and body["graph"]["nodes"][0]["params"]["resolution"] == "15m"
    first = fake.calls[0]["messages"]
    assert [m.role for m in first] == ["user", "assistant", "user"]
    assert "check_strategy" in fake.calls[0]["system"]


@pytest.mark.parametrize(
    "payload, status, detail",
    [
        ({"prompt": "  "}, 400, "Prompt is required"),
        ({"prompt": "hi", "provider": "gemini", "model": "gemini-2.0-flash"}, 400, "Unknown model"),
        ({"prompt": "hi", "graph": {"nodes": [{"id": "x", "type": "log2"}], "edges": []}}, 400, "Canvas graph is not valid"),
    ],
)
def test_llm_route_rejects_bad_requests(client, signed_in, payload, status, detail):
    response = client.post("/llm", json=payload)
    assert response.status_code == status
    assert detail in response.json()["detail"]


def test_llm_route_reports_missing_configuration(client, signed_in, monkeypatch):
    for name in ("AI_PROVIDER", "GEMINI_API_KEY", "META_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    response = client.post("/llm", json={"prompt": "hi", "provider": "meta", "model": "muse-spark-1.3"})
    assert response.status_code == 503 and "META_API_KEY" in response.json()["detail"]

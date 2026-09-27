"""Request bodies. Unknown fields are rejected (422) unless noted."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(BaseModel):
    email: str
    password: str


class StrategyCreate(Strict):
    name: str
    document: dict[str, Any]
    ir: dict[str, Any] | None = None
    visibility: str = "private"


class StrategyUpdate(Strict):
    """Only the fields that are sent are changed (``ir: null`` clears the IR)."""

    name: str | None = None
    document: dict[str, Any] | None = None
    ir: dict[str, Any] | None = None
    visibility: str | None = None


class BacktestCreate(Strict):
    user_id: int
    strategy_id: int


class DiscussionCreate(Strict):
    body: str
    strategy_id: int | None = None
    parent_id: int | None = None


class SummaryRequest(Strict):
    refresh: bool = False


class GraphNode(BaseModel):
    """A canvas block. Editor nodes also carry position, size, and ``data.params``; those are ignored."""

    model_config = ConfigDict(extra="ignore")
    id: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def params_from_editor_node(cls, value: Any) -> Any:
        if isinstance(value, dict) and not isinstance(value.get("params"), dict):
            data = value.get("data")
            if isinstance(data, dict) and isinstance(data.get("params"), dict):
                return {**value, "params": data["params"]}
        return value


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str
    sourceHandle: str
    target: str
    targetHandle: str


class GraphBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nodes: list[GraphNode] = Field(max_length=80)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=160)

    @model_validator(mode="before")
    @classmethod
    def drop_edges_without_ports(cls, value: Any) -> Any:
        # A half-drawn React Flow edge has a null handle; it is not a connection yet.
        if isinstance(value, dict) and isinstance(value.get("edges"), list):
            edges = [e for e in value["edges"] if isinstance(e, dict) and e.get("sourceHandle") and e.get("targetHandle")]
            return {**value, "edges": edges}
        return value


class ChatTurn(Strict):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AssistantAsk(Strict):
    prompt: str
    graph: GraphBody | None = None
    provider: str | None = None
    model: str | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class AnalysisRequest(Strict):
    provider: str | None = None
    model: str | None = None
    question: str = Field(default="", max_length=1000)

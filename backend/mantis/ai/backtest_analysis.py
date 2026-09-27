"""AI analysis of a finished backtest, behind ``POST /backtests/{id}/analysis``.

The model sees the strategy exactly as it was when the run started (the ``backtest``
strategy version), the run's metrics, a sample of the equity curve, and its orders,
and explains the result and what to try next. It uses the same model choices as the
editor's assistant.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.mantis import db
from backend.mantis.ai.client import ChatClient
from backend.mantis.ai.models import resolve_choice
from backend.mantis.ai.prompts import load_prompt
from backend.mantis.ai.providers import AIConfigError, AIProviderError
from backend.mantis.errors import InvalidInput, ServiceUnavailable, UpstreamFailed
from backend.mantis.services import backtests

MAX_QUESTION = 1000
EQUITY_POINTS = 40
MAX_ORDERS = 60

Complete = Callable[[str, str], str]
"""``complete(system_prompt, message) -> model text``."""


def analyze(
    viewer_id: int,
    backtest_id: int,
    *,
    provider: str | None = None,
    model: str | None = None,
    question: str = "",
    complete: Complete | None = None,
) -> dict[str, Any]:
    question = question.strip()
    if len(question) > MAX_QUESTION:
        raise InvalidInput(f"Question is too long (at most {MAX_QUESTION} characters)")
    try:
        chosen_provider, chosen_model = resolve_choice(provider, model)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    report = backtests.get_backtest(viewer_id, backtest_id)
    message = run_text(report, _snapshot(report["strategy_version_id"]), question)
    system = load_prompt("backtest_analysis.md")
    try:
        if complete is not None:
            text, used_model = complete(system, message), chosen_model
        else:
            with ChatClient.from_env(chosen_provider, chosen_model) as client:
                text = client.chat(message, system=system, max_tokens=2048).text
                used_model = client.model
    except AIConfigError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    except AIProviderError as exc:
        raise UpstreamFailed("Analysis service is unavailable") from exc
    if not text.strip():
        raise UpstreamFailed("Analysis service returned an empty answer")
    return {"id": backtest_id, "analysis": text.strip(), "model": used_model}


def run_text(report: dict[str, Any], document: Any, question: str = "") -> str:
    """Everything the model reads about one run, as compact labeled JSON sections."""
    balances = report["balances"]
    step = max(1, len(balances) // EQUITY_POINTS)
    sections = {
        "Strategy blocks": _blocks(document),
        "Run": {
            "strategy": report["strategy_name"],
            "ran_on": report.get("source"),
            "ticks": max(0, len(balances) - 1),
            "from": balances[0]["ts"] if balances else None,
            "to": balances[-1]["ts"] if balances else None,
        },
        "Metrics": report["metrics"],
        "Equity sample (ts, equity)": [[b["ts"], b["equity"]] for b in balances[::step]],
        f"Orders (first {MAX_ORDERS} of {len(report['orders'])})": report["orders"][:MAX_ORDERS],
    }
    text = "\n\n".join(f"{title}:\n{json.dumps(value, separators=(',', ':'), default=str)}" for title, value in sections.items())
    return f"{text}\n\nQuestion from the user:\n{question}" if question else text


def _blocks(document: Any) -> dict[str, Any]:
    """Blocks with their params and the wires between them, without editor layout."""
    flow = document.get("flow") if isinstance(document, dict) else None
    if not isinstance(flow, dict):
        return {}
    nodes = [
        {"id": n.get("id"), "type": n.get("type"), "params": (n.get("data") or {}).get("params", {})}
        for n in flow.get("nodes") or []
        if isinstance(n, dict)
    ]
    wires = [
        f"{e.get('source')}.{e.get('sourceHandle')} -> {e.get('target')}.{e.get('targetHandle')}"
        for e in flow.get("edges") or []
        if isinstance(e, dict)
    ]
    return {"nodes": nodes, "wires": wires}


def _snapshot(version_id: int) -> Any:
    with db.session() as conn:
        row = conn.execute("SELECT document FROM strategy_versions WHERE id = %s", (version_id,)).fetchone()
    return None if row is None else row[0]

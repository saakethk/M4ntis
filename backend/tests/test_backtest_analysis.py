"""AI backtest analysis with the report, snapshot, and model faked."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.mantis.ai import backtest_analysis
from backend.mantis.ai.providers import ChatResponse
from backend.mantis.errors import NotFound
from backend.mantis.services import auth

REPORT = {
    "id": 7,
    "strategy_id": 3,
    "strategy_name": "Z dip",
    "strategy_version_id": 11,
    "source": "fpga",
    "orders": [{"ts": "2026-09-01T14:30:00+00:00", "symbol": "AMD", "side": "buy", "quantity": 10, "price": 150.0}],
    "balances": [{"ts": f"2026-09-01T14:{30 + i}:00+00:00", "cash": 100000.0, "equity": 100000.0 + i} for i in range(20)],
    "metrics": {"return_pct": 0.02, "num_trades": 0, "max_drawdown_pct": 0.0},
}
DOCUMENT = {
    "schema": "m4ntis.strategy/v1",
    "flow": {
        "nodes": [{"id": "z", "type": "z_score", "position": {"x": 5, "y": 9}, "data": {"params": {"n": 20}}}],
        "edges": [{"source": "z", "sourceHandle": "data:out", "target": "i", "targetHandle": "data:a"}],
    },
}


class FakeClient:
    model = "muse-spark-1.3"

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def chat(self, message, **kwargs):
        self.calls.append({"message": message, **kwargs})
        return ChatResponse(text="  It bought once and never sold.  ", provider="meta", model=self.model)


@pytest.fixture
def faked():
    with (
        patch.object(auth, "user_from_token", return_value=auth.User(4, "a@b.com")),
        patch.object(backtest_analysis.backtests, "get_backtest", return_value=REPORT) as get,
        patch.object(backtest_analysis, "_snapshot", return_value=DOCUMENT),
    ):
        yield get


def test_run_text_has_blocks_metrics_and_question_but_no_layout():
    text = backtest_analysis.run_text(REPORT, DOCUMENT, "Why no sells?")
    assert '"type":"z_score"' in text and "z.data:out -> i.data:a" in text
    assert '"num_trades":0' in text and '"ran_on":"fpga"' in text
    assert "position" not in text
    assert text.endswith("Question from the user:\nWhy no sells?")


def test_route_uses_the_chosen_model(client, faked):
    fake = FakeClient()
    with patch("mantis.ai.backtest_analysis.ChatClient.from_env", return_value=fake) as from_env:
        response = client.post("/backtests/7/analysis", json={"provider": "meta", "model": "muse-spark-1.3", "question": "Why?"})
    assert response.status_code == 200, response.text
    assert response.json() == {"id": 7, "analysis": "It bought once and never sold.", "model": "muse-spark-1.3"}
    from_env.assert_called_once_with("meta", "muse-spark-1.3")
    faked.assert_called_once_with(4, 7)
    assert "backtest results" in fake.calls[0]["system"]


def test_route_errors(client, faked, monkeypatch):
    assert client.post("/backtests/7/analysis", json={"model": "gemini-2.0-flash"}).status_code == 400
    for name in ("AI_PROVIDER", "GEMINI_API_KEY", "META_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    missing = client.post("/backtests/7/analysis", json={"provider": "meta", "model": "muse-spark-1.3"})
    assert missing.status_code == 503 and "META_API_KEY" in missing.json()["detail"]
    faked.side_effect = NotFound("Backtest not found")
    assert client.post("/backtests/8/analysis").status_code == 404

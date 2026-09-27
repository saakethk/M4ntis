"""End-to-end flows through the HTTP API against a real PostgreSQL database.

These run only when ``MANTIS_TEST_DATABASE`` is set (see ``conftest.py``).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from src.backend.mantis.services import market_data
from tradecpu.hwtest import FakeBoard

from src.backend.mantis.api.app import create_app
from src.backend.mantis.blocks.canvas import empty_canvas
from src.backend.mantis.blocks.document import document_from_canvas
from src.backend.mantis.services import fpga
from src.backend.tests.conftest import CROSSOVER, sign_up

DOCUMENT = document_from_canvas(empty_canvas(), name="Opening drive")


def new_client() -> TestClient:
    return TestClient(create_app())


def test_accounts_and_sessions(database):
    client = new_client()
    user = sign_up(client, "Ada@Example.com")
    assert user["email"] == "ada@example.com"
    assert client.get("/auth/me").json() == user
    assert new_client().post("/auth/register", json={"email": "ada@example.com", "password": "correct-horse"}).status_code == 409

    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json={"email": "ada@example.com", "password": "wrong-horse"}).status_code == 401
    assert client.post("/auth/login", json={"email": "ada@example.com", "password": "correct-horse"}).status_code == 200
    assert client.get("/auth/me").status_code == 200


def test_strategy_lifecycle_versions_and_visibility(database):
    owner, other = new_client(), new_client()
    sign_up(owner, "owner@example.com")
    sign_up(other, "other@example.com")

    created = owner.post("/strategies", json={"name": " Drive ", "document": DOCUMENT}).json()
    strategy_id = created["id"]
    assert created["name"] == "Drive" and created["visibility"] == "private"
    assert other.get(f"/strategies/{strategy_id}").status_code == 404

    renamed = {**DOCUMENT, "name": "Drive v2"}
    assert owner.put(f"/strategies/{strategy_id}", json={"name": "Drive v2", "document": renamed}).status_code == 200
    versions = owner.get(f"/strategies/{strategy_id}/versions").json()
    assert [v["name"] for v in versions] == ["Drive v2", "Opening drive"]

    reverted = owner.post(f"/strategies/{strategy_id}/versions/{versions[-1]['id']}/revert").json()
    assert reverted["name"] == "Opening drive" and reverted["owned"] is True
    assert len(owner.get(f"/strategies/{strategy_id}/versions").json()) == 3

    owner.put(f"/strategies/{strategy_id}", json={"visibility": "public"})
    viewed = other.get(f"/strategies/{strategy_id}").json()
    assert viewed["owned"] is False
    assert other.put(f"/strategies/{strategy_id}", json={"name": "Mine"}).status_code == 403
    assert other.get(f"/strategies/{strategy_id}/versions").status_code == 403

    copy_id = other.post(f"/strategies/{strategy_id}/copy").json()["id"]
    assert [s["id"] for s in other.get("/strategies").json()] == [copy_id]


def test_compile_saved_strategy_and_invalid_documents(database):
    client = new_client()
    sign_up(client, "c@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": DOCUMENT}).json()["id"]
    compiled = client.post("/compile", json={"strategy_id": strategy_id})
    assert compiled.status_code == 200 and compiled.json()["ok"] is True
    bad = {**DOCUMENT, "flow": {"nodes": [{"id": "x", "type": "nope", "data": {"params": {}}}], "edges": []}}
    rejected = client.post("/compile", json=bad)
    assert rejected.status_code == 400 and rejected.json()["diagnostics"]
    assert client.post("/compile", json={"strategy_id": strategy_id, "extra": 1}).status_code == 422


def aapl_bars(resolution: str, ticks: int) -> list:
    start = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    return [(start + timedelta(minutes=i), [round(150 + 10 * math.sin(i / 5), 2)]) for i in range(min(ticks, 60))]


def fake_board(monkeypatch) -> None:
    monkeypatch.setattr(fpga, "status", lambda: {"connected": True, "port": "/dev/fake", "busy": False, "detail": "Connected at /dev/fake"})
    monkeypatch.setattr(fpga, "open_port", FakeBoard)
    monkeypatch.setattr(market_data, "latest_closes", lambda symbols, resolution, ticks: aapl_bars(resolution, ticks))


def fake_available_range(_symbols):
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 5)]
    return {"start": days[0], "end": days[-1], "days": days}


def fake_closes_between(symbols, resolution, start, end, warmup):
    del symbols, resolution
    base = datetime(start.year, start.month, start.day, 13, 30, tzinfo=timezone.utc)
    warmup_bars = [(base - timedelta(minutes=warmup - i), [150.0]) for i in range(warmup)]
    in_range = [(base + timedelta(days=day), [150.0 + day]) for day in range((end - start).days + 1)]
    return warmup_bars + in_range


def test_backtests_refuse_without_fpga(database, monkeypatch):
    monkeypatch.setenv("FPGA_SERIAL_PORT", "")
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [])
    client = new_client()
    user = sign_up(client, "b@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": CROSSOVER}).json()["id"]
    assert client.get("/backtests/fpga").json()["connected"] is False
    refused = client.post("/backtests", json={"user_id": user["id"], "strategy_id": strategy_id})
    assert refused.status_code == 503 and "FPGA" in refused.json()["detail"]
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM backtests").fetchone()[0] == 0


def test_backtests_run_on_fpga(database, monkeypatch):
    fake_board(monkeypatch)
    client = new_client()
    user = sign_up(client, "b@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": CROSSOVER}).json()["id"]
    assert client.post("/backtests", json={"user_id": user["id"] + 1, "strategy_id": strategy_id}).status_code == 403

    run = client.post("/backtests", json={"user_id": user["id"], "strategy_id": strategy_id})
    assert run.status_code == 201, run.text
    assert run.json()["source"] == "fpga" and run.json()["ticks"] == 60
    report = client.get(f"/backtests/{run.json()['id']}").json()
    assert report["strategy_name"] == "S" and report["source"] == "fpga"
    assert report["orders"] and {o["symbol"] for o in report["orders"]} == {"AAPL"}
    assert len(report["balances"]) == 61 and report["balances"][0]["cash"] == 10000
    assert report["metrics"]["num_trades"] > 0
    assert new_client().get(f"/backtests/{run.json()['id']}").status_code == 401


def test_backtest_range_endpoint(database, monkeypatch):
    fake_board(monkeypatch)
    monkeypatch.setattr(market_data, "available_range", fake_available_range)
    client = new_client()
    user = sign_up(client, "range@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": CROSSOVER}).json()["id"]
    payload = client.get(f"/backtests/range?strategy_id={strategy_id}").json()
    assert payload["symbols"] == ["AAPL"]
    assert payload["start"] == "2024-01-02"
    assert payload["days"] == ["2024-01-02", "2024-01-03", "2024-01-05"]


def test_backtests_with_custom_range(database, monkeypatch):
    fake_board(monkeypatch)
    monkeypatch.setattr(market_data, "available_range", fake_available_range)
    monkeypatch.setattr(market_data, "closes_between", fake_closes_between)
    client = new_client()
    user = sign_up(client, "range-run@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": CROSSOVER}).json()["id"]
    run = client.post(
        "/backtests",
        json={"user_id": user["id"], "strategy_id": strategy_id, "start": "2024-01-02", "end": "2024-01-03"},
    )
    assert run.status_code == 201, run.text
    report = client.get(f"/backtests/{run.json()['id']}").json()
    assert report["range_start"] == "2024-01-02"
    assert report["range_end"] is not None


def test_backtests_reject_bad_range(database, monkeypatch):
    fake_board(monkeypatch)
    monkeypatch.setattr(market_data, "available_range", fake_available_range)
    client = new_client()
    user = sign_up(client, "bad-range@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": CROSSOVER}).json()["id"]
    bad = client.post(
        "/backtests",
        json={"user_id": user["id"], "strategy_id": strategy_id, "start": "2024-01-06", "end": "2024-01-06"},
    )
    assert bad.status_code == 400
    assert "2024-01-02" in bad.json()["detail"] and "2024-01-05" in bad.json()["detail"]
    reversed_ = client.post(
        "/backtests",
        json={"user_id": user["id"], "strategy_id": strategy_id, "start": "2024-01-05", "end": "2024-01-02"},
    )
    assert reversed_.status_code == 400 and "start" in reversed_.json()["detail"].lower()


def test_backtests_wait_for_a_busy_fpga(database, monkeypatch):
    fake_board(monkeypatch)
    client = new_client()
    user = sign_up(client, "b@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": CROSSOVER}).json()["id"]
    with fpga.board():
        busy = client.post("/backtests", json={"user_id": user["id"], "strategy_id": strategy_id})
    assert busy.status_code == 409 and "busy" in busy.json()["detail"]


def test_discussions_publish_like_and_summaries(database):
    author, reader = new_client(), new_client()
    sign_up(author, "author@example.com")
    sign_up(reader, "reader@example.com")
    strategy_id = author.post("/strategies", json={"name": "Shared", "document": DOCUMENT}).json()["id"]

    assert reader.post("/discussions", json={"body": "mine now", "strategy_id": strategy_id}).status_code == 403
    post = author.post("/discussions", json={"body": "Try this", "strategy_id": strategy_id}).json()
    assert post["strategy_made_public"] is True
    reader.post("/discussions", json={"body": "Nice!", "parent_id": post["id"]})

    liked = reader.post(f"/discussions/{post['id']}/like").json()
    assert liked == {"id": post["id"], "likes_count": 1, "liked": True}
    assert reader.post(f"/discussions/{post['id']}/like").json()["liked"] is False

    calls = []

    def fake_summary(thread):
        calls.append(thread)
        return f"{len(thread.replies)} replies about {thread.strategy_name}", "muse-spark-1.3"

    with patch("mantis.api.routes.discussions.summarize_thread", side_effect=fake_summary):
        first = reader.post(f"/discussions/{post['id']}/summary").json()
        cached = reader.post(f"/discussions/{post['id']}/summary").json()
        reader.post("/discussions", json={"body": "Does it work on 1h?", "parent_id": post["id"]})
        listed = {p["id"]: p for p in reader.get("/discussions").json()}
        assert listed[post["id"]]["summary"]["stale"] is True
        fresh = reader.post(f"/discussions/{post['id']}/summary").json()

    assert first == {"id": post["id"], "summary": "1 replies about Shared", "model": "muse-spark-1.3", "cached": False}
    assert cached["cached"] is True
    assert fresh["summary"].startswith("2 replies") and len(calls) == 2
    assert calls[0].strategy_blocks == {"start": 1}
    assert reader.post("/discussions/999999/summary").status_code == 404

"""End-to-end flows through the HTTP API against a real PostgreSQL database.

These run only when ``MANTIS_TEST_DATABASE`` is set (see ``conftest.py``).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from mantis.api.app import create_app
from mantis.blocks.document import document_from_canvas
from mantis.blocks.canvas import empty_canvas
from tests.conftest import sign_up

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


def test_backtests(database):
    client = new_client()
    user = sign_up(client, "b@example.com")
    strategy_id = client.post("/strategies", json={"name": "S", "document": DOCUMENT}).json()["id"]
    assert client.post("/backtests", json={"user_id": user["id"] + 1, "strategy_id": strategy_id}).status_code == 403
    run = client.post("/backtests", json={"user_id": user["id"], "strategy_id": strategy_id})
    assert run.status_code == 201
    report = client.get(f"/backtests/{run.json()['id']}").json()
    assert report["strategy_name"] == "S"
    assert report["metrics"]["num_trades"] == 1 and report["metrics"]["trade_returns"] == [60.0]
    assert new_client().get(f"/backtests/{run.json()['id']}").status_code == 401


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

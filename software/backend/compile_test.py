"""Compile route tests that do not require Tiger Data."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import helpers.auth as auth
import helpers.compile as compiler
import helpers.strategies as strategies
import main
from helpers.auth import User

OWNER = User(4, "owner@example.com")

BLANK = {
    "schema": "m4ntis.strategy/v1",
    "name": "Blank",
    "savedAt": "",
    "flow": {
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "position": {"x": 0, "y": 0},
                "data": {
                    "params": {
                        "startingBalance": 100000,
                        "resolution": "5m",
                        "symbol0": "AAPL",
                        "symbol1": "",
                        "symbol2": "",
                        "symbol3": "",
                        "symbol4": "",
                    }
                },
            }
        ],
        "edges": [],
    },
}

STORED = {
    **BLANK,
    "name": "Stored",
}

IR = {
    "schema": "m4ntis.strategy-ir/v1",
    "entry": "start",
    "nodes": [],
}


def _sign_in(client: TestClient) -> None:
    client.cookies.set("session", "raw-token")


class CompileDocumentTest(unittest.TestCase):
    def test_blank_document_matches_the_compiler_json(self) -> None:
        result = compiler.compile_document(BLANK)
        self.assertTrue(result["ok"])
        self.assertIn("SETBALANCE", result["asm"])
        self.assertIn("EMITBALANCE", result["asm"])
        self.assertTrue(result["hex"].strip())
        self.assertEqual(result["manifest"]["schema"], "m4ntis.compiled/v1")
        self.assertEqual(result["manifest"]["name"], "Blank")
        self.assertEqual(result["diagnostics"], [])


class CompileRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_compile_requires_a_session(self) -> None:
        with patch.object(auth, "user_from_token", return_value=None):
            document = self.client.post("/compile", json=BLANK)
            saved = self.client.post("/compile", json={"strategy_id": 8})
            ir = self.client.post("/compile", json=IR)
        self.assertEqual(
            [document.status_code, saved.status_code, ir.status_code],
            [401, 401, 401],
        )

    def test_wrapper_rejects_extra_fields(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            extra = self.client.post(
                "/compile", json={"strategy_id": 8, "name": "Trend"}
            )
            share = self.client.post(
                "/compile", json={"document": BLANK, "user_id": 4}
            )
        self.assertEqual(extra.status_code, 422)
        self.assertEqual(share.status_code, 422)

    def test_missing_document_and_strategy_id_is_rejected(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.post("/compile", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("document", response.json()["detail"])

    def test_document_compiles_with_the_real_compiler(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.post("/compile", json=BLANK)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("SETBALANCE", body["asm"])
        self.assertEqual(body["manifest"]["schema"], "m4ntis.compiled/v1")
        self.assertEqual(body["manifest"]["name"], "Blank")

    def test_ir_returns_the_compiler_message(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.post("/compile", json=IR)
        self.assertEqual(response.status_code, 400)
        self.assertIn("m4ntis.strategy/v1", response.json()["detail"])
        self.assertNotIn("Traceback", response.text)

    def test_malformed_document_is_a_client_error(self) -> None:
        _sign_in(self.client)
        bad = {"schema": "m4ntis.strategy/v1", "name": "Bad", "flow": [1]}
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.post("/compile", json=bad)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Traceback", response.text)

    def test_strategy_id_compiles_the_stored_document_when_viewable(self) -> None:
        _sign_in(self.client)
        stored = {"document": STORED}
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "get_strategy", return_value=stored) as fetch,
        ):
            response = self.client.post("/compile", json={"strategy_id": 8})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["manifest"]["name"], "Stored")
        fetch.assert_called_once_with(OWNER.id, 8)

    def test_strategy_id_with_a_document_compiles_that_document(self) -> None:
        _sign_in(self.client)
        stored = {"document": STORED}
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "get_strategy", return_value=stored) as fetch,
        ):
            response = self.client.post(
                "/compile", json={"strategy_id": 8, "document": BLANK}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["manifest"]["name"], "Blank")
        fetch.assert_called_once_with(OWNER.id, 8)

    def test_strategy_id_on_a_document_still_requires_view_access(self) -> None:
        _sign_in(self.client)
        body = {**BLANK, "strategy_id": 8}
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "get_strategy", side_effect=strategies.StrategyNotFound
            ),
            patch.object(compiler, "compile_strategy") as compile_strategy,
        ):
            response = self.client.post("/compile", json=body)
        self.assertEqual(response.status_code, 404)
        compile_strategy.assert_not_called()

    def test_hidden_strategy_is_not_compiled(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "get_strategy", side_effect=strategies.StrategyNotFound
            ),
            patch.object(compiler, "compile_strategy") as compile_strategy,
        ):
            response = self.client.post("/compile", json={"strategy_id": 8})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Strategy not found")
        compile_strategy.assert_not_called()

    def test_strategy_lookup_failure_does_not_compile(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "get_strategy", side_effect=RuntimeError("db down")
            ),
            patch.object(compiler, "compile_strategy") as compile_strategy,
        ):
            response = self.client.post("/compile", json={"strategy_id": 8})
        self.assertEqual(response.status_code, 503)
        compile_strategy.assert_not_called()


if __name__ == "__main__":
    unittest.main()

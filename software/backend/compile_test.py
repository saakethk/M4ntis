"""Compile route tests that do not require Tiger Data."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
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

SMA_CROSSOVER = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "frontend/dev-sketchout/examples/sma_crossover.strategy.json"
    ).read_text()
)

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

    def test_example_strategy_compiles_to_uploadable_words(self) -> None:
        result = compiler.compile_document(SMA_CROSSOVER)
        words = result["manifest"]["words"]
        self.assertGreater(len(words), 10)
        self.assertTrue(all(w.startswith("0x") and len(w) == 10 for w in words))
        self.assertEqual(result["manifest"]["warmupTicks"], 29)

    def test_price_exponents_reach_the_manifest(self) -> None:
        result = compiler.compile_document(SMA_CROSSOVER, {0: 1})
        exponents = [b["priceExponent"] for b in result["manifest"]["buffers"]]
        self.assertEqual(exponents, [1, 2, 2, 2, 2])

    def test_rejection_carries_node_diagnostics(self) -> None:
        document = copy.deepcopy(SMA_CROSSOVER)
        sma = next(n for n in document["flow"]["nodes"] if n["type"] == "sma")
        sma["data"]["params"]["n"] = 99
        with self.assertRaises(compiler.CompilationFailed) as ctx:
            compiler.compile_document(document)
        self.assertEqual(ctx.exception.diagnostics[0]["node"], sma["id"])
        self.assertIn(f"[{sma['id']}]", str(ctx.exception))


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
        self.assertIn("flow must be an object", response.json()["detail"])

    def test_rejected_strategy_returns_diagnostics(self) -> None:
        _sign_in(self.client)
        document = copy.deepcopy(SMA_CROSSOVER)
        document["flow"]["edges"] = [
            e for e in document["flow"]["edges"] if e["targetHandle"] != "data:a"
        ]
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.post("/compile", json=document)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["diagnostics"][0]["level"], "error")
        self.assertIn("node", body["diagnostics"][0])

    def test_price_exponents_in_the_wrapper(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            ok = self.client.post(
                "/compile", json={"document": SMA_CROSSOVER, "price_exponents": {"0": 1}}
            )
            bad = self.client.post(
                "/compile", json={"document": SMA_CROSSOVER, "price_exponents": {"7": 1}}
            )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["manifest"]["buffers"][0]["priceExponent"], 1)
        self.assertEqual(bad.status_code, 400)
        self.assertIn("BUF7", bad.json()["detail"])

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
            patch.object(compiler, "compile_to_json") as compile_to_json,
        ):
            response = self.client.post("/compile", json=body)
        self.assertEqual(response.status_code, 404)
        compile_to_json.assert_not_called()

    def test_hidden_strategy_is_not_compiled(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "get_strategy", side_effect=strategies.StrategyNotFound
            ),
            patch.object(compiler, "compile_to_json") as compile_to_json,
        ):
            response = self.client.post("/compile", json={"strategy_id": 8})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Strategy not found")
        compile_to_json.assert_not_called()

    def test_strategy_lookup_failure_does_not_compile(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "get_strategy", side_effect=RuntimeError("db down")
            ),
            patch.object(compiler, "compile_to_json") as compile_to_json,
        ):
            response = self.client.post("/compile", json={"strategy_id": 8})
        self.assertEqual(response.status_code, 503)
        compile_to_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()

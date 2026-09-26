"""Strategy visibility tests that do not require Tiger Data."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import helpers.auth as auth
import helpers.strategies as strategies
import main
from helpers.auth import User

SOFTWARE = Path(__file__).resolve().parents[1]
DOCUMENT = {"kind": "m4ntis.strategy/v1", "nodes": []}
IR = {"kind": "m4ntis.strategy-ir/v1", "ops": []}
OWNER = User(4, "owner@example.com")


def _sign_in(client: TestClient) -> None:
    client.cookies.set("session", "raw-token")


class VisibilityRulesTest(unittest.TestCase):
    def test_private_strategy_is_visible_only_to_its_owner(self) -> None:
        self.assertTrue(strategies.can_view(1, "private", 1))
        self.assertFalse(strategies.can_view(1, "private", 2))
        self.assertTrue(strategies.can_edit(1, 1))
        self.assertFalse(strategies.can_edit(1, 2))

    def test_public_strategy_is_viewable_and_still_owner_edited(self) -> None:
        self.assertTrue(strategies.can_view(1, "public", 2))
        self.assertFalse(strategies.can_edit(1, 2))
        self.assertTrue(strategies.can_edit(1, 1))

    def test_visibility_rejects_share_roles(self) -> None:
        for value in ("view", "edit", "shared", "", None):
            with self.assertRaises(ValueError):
                strategies.normalize_visibility(value)
        self.assertEqual(strategies.normalize_visibility("private"), "private")
        self.assertEqual(strategies.normalize_visibility("public"), "public")

    def test_new_strategy_is_private(self) -> None:
        values = strategies.new_strategy_values(9, "  Trend  ", DOCUMENT, None)
        self.assertEqual(values["user_id"], 9)
        self.assertEqual(values["name"], "Trend")
        self.assertEqual(values["visibility"], "private")
        self.assertEqual(values["document"], DOCUMENT)
        self.assertIsNone(values["ir"])

    def test_copy_is_a_private_row_for_the_caller(self) -> None:
        document = {"nodes": [1]}
        ir = {"ops": [2]}
        payload = strategies.copy_payload(9, "Trend", document, ir)
        self.assertEqual(
            payload,
            {
                "user_id": 9,
                "name": "Trend",
                "visibility": "private",
                "document": {"nodes": [1]},
                "ir": {"ops": [2]},
            },
        )
        payload["document"]["nodes"].append(3)
        payload["ir"]["ops"].append(4)
        self.assertEqual(document, {"nodes": [1]})
        self.assertEqual(ir, {"ops": [2]})

    def test_list_query_omits_the_document(self) -> None:
        folded = " ".join(strategies.LIST_SQL.split())
        self.assertNotIn("document", folded)
        self.assertNotIn("ir", folded)
        self.assertIn("id, name, visibility, updated_at", folded)

    def test_schema_uses_visibility_and_the_loader_drops_shares(self) -> None:
        sql = (SOFTWARE / "database" / "sql" / "strategies.sql").read_text()
        loader = (SOFTWARE / "database" / "load_strategies.py").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS strategies", sql)
        self.assertIn("visibility TEXT NOT NULL DEFAULT 'private'", sql)
        self.assertIn("CHECK (visibility IN ('private', 'public'))", sql)
        self.assertIn("strategies_user_id_idx", sql)
        self.assertNotIn("strategy_shares", sql)
        self.assertIn("DROP TABLE IF EXISTS strategy_shares", loader)
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'",
            loader,
        )
        self.assertIn("strategies_visibility_check", loader)
        self.assertIn("if existing is not None", loader)


class StrategyRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_routes_require_a_session(self) -> None:
        with patch.object(auth, "user_from_token", return_value=None):
            created = self.client.post(
                "/strategies", json={"name": "Trend", "document": DOCUMENT}
            )
            listed = self.client.get("/strategies")
            fetched = self.client.get("/strategies/1")
            updated = self.client.put("/strategies/1", json={"name": "Trend"})
            copied = self.client.post("/strategies/1/copy")
        self.assertEqual(
            [created.status_code, listed.status_code, fetched.status_code, updated.status_code, copied.status_code],
            [401, 401, 401, 401, 401],
        )

    def test_create_stores_a_private_strategy_for_the_session_user(self) -> None:
        stored = {
            "id": 3,
            "user_id": 4,
            "name": "Trend",
            "visibility": "private",
            "document": DOCUMENT,
            "ir": IR,
            "updated_at": "2026-09-26T00:00:00+00:00",
            "created_at": "2026-09-26T00:00:00+00:00",
            "owned": True,
        }
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "create_strategy", return_value=stored) as create,
        ):
            response = self.client.post(
                "/strategies", json={"name": "Trend", "document": DOCUMENT, "ir": IR}
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["visibility"], "private")
        self.assertTrue(response.json()["owned"])
        create.assert_called_once_with(4, "Trend", DOCUMENT, IR)

    def test_create_rejects_share_fields(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            role = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "role": "edit"},
            )
            share = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "share_with_user": 8},
            )
        self.assertEqual(role.status_code, 422)
        self.assertEqual(share.status_code, 422)

    def test_list_returns_summaries_without_documents(self) -> None:
        summaries = [
            {
                "id": 3,
                "name": "Trend",
                "visibility": "private",
                "updated_at": "2026-09-26T00:00:00+00:00",
            }
        ]
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "list_strategies", return_value=summaries),
        ):
            response = self.client.get("/strategies")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), summaries)
        self.assertNotIn("document", response.json()[0])

    def test_get_returns_the_document_and_owned_flag(self) -> None:
        row = {
            "id": 3,
            "user_id": 9,
            "name": "Trend",
            "visibility": "public",
            "document": DOCUMENT,
            "ir": None,
            "updated_at": "2026-09-26T00:00:00+00:00",
            "created_at": "2026-09-26T00:00:00+00:00",
            "owned": False,
        }
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "get_strategy", return_value=row),
        ):
            response = self.client.get("/strategies/3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["document"], DOCUMENT)
        self.assertFalse(response.json()["owned"])

    def test_get_hides_strategies_the_user_cannot_view(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "get_strategy", side_effect=strategies.StrategyNotFound()),
        ):
            response = self.client.get("/strategies/3")
        self.assertEqual(response.status_code, 404)

    def test_put_rejects_non_owners_and_bad_visibility(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "update_strategy", side_effect=strategies.StrategyForbidden()
            ) as update,
        ):
            forbidden = self.client.put("/strategies/3", json={"visibility": "public"})
        self.assertEqual(forbidden.status_code, 403)
        update.assert_called_once()

        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "update_strategy") as update,
        ):
            rejected = self.client.put("/strategies/3", json={"visibility": "edit"})
        self.assertEqual(rejected.status_code, 400)
        update.assert_not_called()

        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "update_strategy", side_effect=strategies.StrategyNotFound()),
        ):
            missing = self.client.put("/strategies/99", json={"name": "Trend"})
        self.assertEqual(missing.status_code, 404)

    def test_put_rejects_a_share_field(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.put(
                "/strategies/3", json={"visibility": "public", "role": "edit"}
            )
        self.assertEqual(response.status_code, 422)

    def test_copy_returns_the_new_id(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "copy_strategy", return_value=12) as copy,
        ):
            response = self.client.post("/strategies/3/copy")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": 12})
        copy.assert_called_once_with(4, 3)

    def test_copy_is_not_found_when_the_user_cannot_view(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "copy_strategy", side_effect=strategies.StrategyNotFound()),
        ):
            response = self.client.post("/strategies/3/copy")
        self.assertEqual(response.status_code, 404)

    def test_database_outage_is_a_service_error(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "list_strategies", side_effect=RuntimeError("missing env")),
        ):
            response = self.client.get("/strategies")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()

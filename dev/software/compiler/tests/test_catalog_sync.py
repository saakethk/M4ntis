"""The frontend catalog and the compiler's block specs must agree, and every exported
template must compile. Both read the frontend's `npm run export:examples` output."""

import json
import unittest
from pathlib import Path

from dev.software.compiler.tradecpu import compile_strategy
from dev.software.compiler.tradecpu.blocks import BLOCKS, UNSUPPORTED
from dev.software.compiler.tradecpu.isa import PROGRAM_WORDS

EXAMPLES = Path(__file__).resolve().parents[2] / "frontend" / "dev-sketchout" / "examples"
CATALOG = EXAMPLES / "block_catalog.json"


def _ports(defn, kind, direction):
    return tuple(
        p["id"].split(":", 1)[1] for p in defn["ports"] if p["kind"] == kind and p["direction"] == direction
    )


@unittest.skipUnless(CATALOG.exists(), "run `npm run export:examples` in dev-sketchout first")
class CatalogSyncTest(unittest.TestCase):
    catalog: dict

    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text())

    def test_same_block_types(self):
        self.assertEqual(set(self.catalog), set(BLOCKS))

    def test_ports_match(self):
        for type_, defn in self.catalog.items():
            spec = BLOCKS[type_]
            with self.subTest(type_):
                self.assertEqual(bool(_ports(defn, "exec", "in")), spec.exec_in)
                self.assertEqual(_ports(defn, "exec", "out"), spec.exec_outs)
                self.assertEqual(_ports(defn, "data", "in"), spec.data_ins)
                self.assertEqual(_ports(defn, "data", "out"), spec.data_outs)

    def test_params_match(self):
        for type_, defn in self.catalog.items():
            spec = BLOCKS[type_]
            params = {p["key"]: p for p in defn["params"]}
            with self.subTest(type_):
                self.assertEqual(set(params), set(spec.params))
                for key, p in params.items():
                    want = spec.params[key]
                    if p["type"] == "number" and want.kind in ("int", "number"):
                        if want.lo is not None:
                            self.assertEqual(p.get("min"), want.lo, key)
                        if want.hi is not None:
                            self.assertEqual(p.get("max"), want.hi, key)
                    elif want.kind == "choice":
                        self.assertEqual(tuple(o["value"] for o in p["options"]), want.choices, key)
                    elif want.kind == "int":
                        values = [o["value"] for o in p["options"]]
                        self.assertEqual((min(values), max(values)), (want.lo, want.hi), key)

    def test_history_and_status_match(self):
        for type_, defn in self.catalog.items():
            with self.subTest(type_):
                self.assertEqual(defn.get("history"), BLOCKS[type_].history)
                self.assertEqual(defn["status"] == "blocked", type_ in UNSUPPORTED)


@unittest.skipUnless(CATALOG.exists(), "run `npm run export:examples` in dev-sketchout first")
class ExampleTemplatesTest(unittest.TestCase):
    def test_every_template_compiles(self):
        files = sorted(EXAMPLES.glob("*.strategy.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                result = compile_strategy(json.loads(path.read_text()))
                self.assertLessEqual(len(result.words), PROGRAM_WORDS)


if __name__ == "__main__":
    unittest.main()

"""Collector/checker software fixtures; NO native application/model execution.

The fake worker constructs public-input structural fixtures, not real Rasa
predictions. Temporary records are deleted after each test and cannot serve as
scientific observations. No Docker process, backend or network is started.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
import copy
import inspect
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiment.transfer_v9 import collect, register
from experiment.transfer_v9.common import HERE, sha
from experiment.transfer_v9.runtime.ledger import zeros
from experiment.transfer_v9.runtime.vanna_native import semantic_rows_equal, reference_check


class SoftwareLedger:
    def __init__(self):
        self.reservations, self.settlements = {}, {}

    def reserve(self, ident, role, requested, metadata):
        if ident in self.reservations:
            raise AssertionError("Duplicate software reservation")
        self.reservations[ident] = {"resources": copy.deepcopy(requested), "role": role,
                                   "metadata": copy.deepcopy(metadata)}

    def settle(self, ident, actual, *, status, evidence):
        if ident not in self.reservations or ident in self.settlements:
            raise AssertionError("Missing/duplicate software settlement")
        self.settlements[ident] = {"resources": copy.deepcopy(actual), "status": status,
                                   "evidence": copy.deepcopy(evidence)}


class FakeRasaWorker:
    instances = []
    requests = []

    def __init__(self, run, cohort, state, ledger):
        self.run, self.cohort, self.state, self.ledger = Path(run), cohort, state, ledger
        self.directory = self.run / cohort / "rasa-workers" / state
        self.directory.mkdir(parents=True, exist_ok=False)
        self.catalog = json.loads((HERE / f"cohorts/{cohort}/rasa.public.json").read_text(encoding="utf-8"))
        assert set(self.catalog) == {"application_id", "training_examples", "tasks"}
        assert all(set(task) == {"task_id", "kind", "input"} for task in self.catalog["tasks"])
        self.tasks = {t["task_id"]: t for t in self.catalog["tasks"]}
        self.training_labels = {row["text"]: row["intent"] for row in self.catalog["training_examples"]}
        self.classes = sorted(set(self.training_labels.values()))
        self.closed, self.close_count = False, 0
        self.seen = set()
        operation = f"{cohort}-rasa-startup-{state}"
        ledger.reserve(operation, "setup", {**zeros(), "end_to_end_seconds": .01}, {"software_fixture": True})
        setup = self.directory / "SETUP.json"
        setup.write_text(json.dumps({"software_fixture": True, "outer_setup_seconds": .01}), encoding="utf-8")
        ledger.settle(operation, {**zeros(), "end_to_end_seconds": .01}, status="completed", evidence={"software_fixture": True})
        self.instances.append(self)

    def query(self, operation, task_id):
        assert not self.closed
        assert isinstance(operation, str) and isinstance(task_id, str)
        assert operation not in self.seen
        self.seen.add(operation)
        self.requests.append({"operation_id": operation, "task_id": task_id})
        task = self.tasks[task_id]
        public = task["input"]
        if task["kind"] == "form":
            blocked = (self.state == "A" and public["conditional_mapping"]
                       and public["prefilled_value"] is None and public["include_entity"])
            value = public["entity_value"] if public["include_entity"] and not blocked else public["prefilled_value"]
            output = {"slot_value": value, "requested_slot": public["slot_name"] if value is None else None,
                      "active_loop": public["form_name"] if value is None else None}
            paths = ["rasa/core/actions/forms.py", "rasa/core/actions/loops.py"]
        else:
            # Public training labels generate an explicitly fake probability
            # vector, solely to exercise collector/reference data plumbing.
            winner = self.training_labels[public["text"]]
            vector = [{"name": name, "confidence": .8 if name == winner else .2/(len(self.classes)-1)}
                      for name in self.classes]
            if self.state == "B":
                ranking = sorted(vector[:10], key=lambda row: -row["confidence"])
            else:
                ranking = sorted(vector, key=lambda row: -row["confidence"])[:10]
            output = {"intent": {"name": winner, "confidence": .8}, "intent_ranking": ranking}
            paths = ["rasa/nlu/classifiers/logistic_regression_classifier.py"]
        return {"event": "query", "operation_id": operation, "task_id": task_id,
                "software_fixture": True, "output": output, "trace": {"production_paths": paths}}

    def close(self):
        self.close_count += 1
        self.closed = True
        (self.directory / "CLOSED.json").write_text(json.dumps({"software_fixture": True, "closed": True}), encoding="utf-8")


class CollectorIntegrationTests(unittest.TestCase):
    def test_full_128_request_frame_reuses_exactly_three_workers_and_binds_raw(self):
        FakeRasaWorker.instances, FakeRasaWorker.requests = [], []
        frame = json.loads((HERE / "cohorts/FRAME.json").read_text(encoding="utf-8"))["validation"]["rasa"]
        ledger = SoftwareLedger()
        with tempfile.TemporaryDirectory(prefix="tosem-collector-software-audit-") as directory:
            root = Path(directory)
            run = root / "fixture-run"
            with patch.object(collect, "ROOT", root), patch.object(collect, "RasaWorker", FakeRasaWorker), redirect_stdout(io.StringIO()):
                records = collect.acquire(run, ledger, "validation", "rasa", frame)
            self.assertEqual(len(records), 128)
            self.assertEqual(len(FakeRasaWorker.instances), 3)
            self.assertEqual({worker.state for worker in FakeRasaWorker.instances}, {"H", "A", "B"})
            self.assertTrue(all(worker.closed and worker.close_count == 1 for worker in FakeRasaWorker.instances))
            self.assertTrue(all((worker.directory / "CLOSED.json").is_file() for worker in FakeRasaWorker.instances))
            self.assertEqual(len(FakeRasaWorker.requests), 128)
            self.assertTrue(all(set(row) == {"operation_id", "task_id"} for row in FakeRasaWorker.requests))
            self.assertEqual(len({row["operation_id"] for row in FakeRasaWorker.requests}), 128)
            self.assertEqual(len(ledger.reservations), 131)
            self.assertEqual(len(ledger.settlements), 131)
            self.assertEqual(sum(row["resources"]["queryfree_native_check_units"] for row in ledger.settlements.values()), 128)
            self.assertEqual(sum(row["resources"]["native_query_units"] for row in ledger.settlements.values()), 0)
            self.assertEqual(sum(row["resources"]["provider_chat_units"] for row in ledger.settlements.values()), 0)
            self.assertEqual(len(list((run / "validation/raw").glob("*.json"))), 128)
            self.assertEqual(sum(record["frame_role"] == "primary_bank" for record in records), 96)
            self.assertEqual(sum(record["frame_role"] == "fresh_confirmation" for record in records), 32)
            self.assertEqual(sum(not record["contract_pass"] for record in records), 16)
            for record, item in zip(records, frame):
                path = root / record["raw_path"]
                receipt = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(sha(path), record["raw_sha256"])
                self.assertEqual(sha(path), record["receipt_sha256"])
                self.assertEqual(ledger.settlements[record["record_id"]]["evidence"]["raw_sha256"], sha(path))
                self.assertEqual(receipt["frame"], item)
                self.assertTrue(receipt["native_output"]["software_fixture"])
                self.assertTrue(receipt["reference_not_supplied_to_application_or_selector"])
                self.assertEqual(receipt["provider_call_ids"], [])
                self.assertEqual(record["contract_pass"], receipt["reference"]["reference_pass"])
                self.assertTrue(record["observed_dependency_tokens"])


class CheckerRegressionTests(unittest.TestCase):
    def test_form_missing_required_nullable_field_fails(self):
        catalog = json.loads((HERE / "cohorts/validation/rasa.private.json").read_text(encoding="utf-8"))
        task = next(task for task in catalog["tasks"] if task["task_id"] == "RF01")
        valid = {"slot_value": "London", "requested_slot": None, "active_loop": None}
        self.assertTrue(collect.rasa_check(task, {"output": valid})["reference_pass"])
        for key in valid:
            with self.subTest(missing=key):
                broken = {name: value for name, value in valid.items() if name != key}
                self.assertFalse(collect.rasa_check(task, {"output": broken})["reference_pass"])

    def test_semantic_scalar_equality_accepts_integer_float_equivalence(self):
        self.assertTrue(semantic_rows_equal([[1.0, 100.0], [2.0, 220.0]], [[2, 220], [1, 100]]))
        self.assertFalse(semantic_rows_equal([[1, 100], [2, 220]], [[1, 220], [2, 100]]))
        self.assertFalse(semantic_rows_equal([[1, 100], [1, 100]], [[1, 100]]))
        self.assertFalse(semantic_rows_equal([[True]], [[1]]))
        self.assertFalse(semantic_rows_equal([["1"]], [[1]]))
        self.assertFalse(semantic_rows_equal([[float("nan")]], [[1]]))
        self.assertFalse(semantic_rows_equal([[float("inf")]], [[1]]))

    def test_floating_plot_coordinates_preserve_exact_reference_pairs(self):
        task = {"family": "figure", "expected_rows": [[1, 100], [2, 220]]}
        observed = {"rows": [[1.0, 100.0], [2.0, 220.0]], "error": None,
                    "figure": {"data": [{"type": "scatter", "x": [2.0, 1.0], "y": [220.0, 100.0]}]}}
        self.assertTrue(reference_check(task, observed)["reference_pass"])
        observed["figure"]["data"][0]["y"] = [100.0, 220.0]
        self.assertFalse(reference_check(task, observed)["reference_pass"])


class RuntimeAuthorityClosureTests(unittest.TestCase):
    def test_registration_paths_include_both_runtime_authorities_and_jinja(self):
        tree = ast.parse(inspect.getsource(register.register))
        appended_paths = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
                    and node.target.id == "paths" and isinstance(node.value, ast.List)):
                for item in node.value.elts:
                    if (isinstance(item, ast.BinOp) and isinstance(item.op, ast.Div)
                            and isinstance(item.left, ast.Name) and item.left.id == "ROOT"
                            and isinstance(item.right, ast.Constant) and isinstance(item.right.value, str)):
                        appended_paths.add(item.right.value)
        expected = {"experiment/runs/development_v8_20261101/backend/ASSET_RECHECK.json",
                    "experiment/runs/development_v8_20261101/backend/START_RECEIPT.json",
                    "experiment/native_v3/provider_llamacpp/qwen2_5_7b_official.jinja"}
        self.assertTrue(expected <= appended_paths)
        freeze_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == "freeze"]
        self.assertEqual(len(freeze_calls), 1)
        self.assertIsInstance(freeze_calls[0].args[0], ast.BinOp)
        self.assertIsInstance(freeze_calls[0].args[0].left, ast.Name)
        self.assertEqual(freeze_calls[0].args[0].left.id, "paths")


if __name__ == "__main__":
    unittest.main()

"""Software/source checks only. This module executes no Rasa application code."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .rasa_native import (
    BASE_PIN, NativeAuthorityError, docker_command, public_catalog,
    source_authority, validate_input,
)


WORKSPACE = Path(__file__).resolve().parents[3]
SOURCE = WORKSPACE / "experiment/transfer_v9/upstream" / f"rasa-{BASE_PIN}"
INVENTORY = WORKSPACE / "experiment/transfer_v9/screening/CASE_INVENTORY.json"
CATALOG = WORKSPACE / "experiment/transfer_v9/screening/RASA_TASK_CATALOG.json"


class NativeInputTests(unittest.TestCase):
    def test_catalog_removes_contracts_and_fault_labels(self):
        catalog = public_catalog(CATALOG)
        self.assertEqual(len(catalog["tasks"]), 8)
        self.assertGreaterEqual(len({row["intent"] for row in catalog["training_examples"]}), 12)
        for task in catalog["tasks"]:
            self.assertEqual(set(task), {"task_id", "kind", "input"})

    def test_exact_module_bindings_exist_and_differ_between_states(self):
        fixed, fixed_modules = source_authority(WORKSPACE, SOURCE, INVENTORY, "fixed", "fixed")
        parent, parent_modules = source_authority(WORKSPACE, SOURCE, INVENTORY, "parent", "parent")
        self.assertEqual(len(fixed_modules), 3)
        self.assertEqual(set(fixed_modules), set(parent_modules))
        self.assertEqual(fixed["source_closure_sha256"], parent["source_closure_sha256"])
        self.assertNotEqual(fixed["authority_sha256"], parent["authority_sha256"])
        for path in fixed["module_proofs"]:
            self.assertNotEqual(fixed["module_proofs"][path]["sha256"],
                                parent["module_proofs"][path]["sha256"])

    def test_wrong_source_pin_or_state_rejected(self):
        with self.assertRaises(NativeAuthorityError):
            source_authority(WORKSPACE, SOURCE, INVENTORY, "mutant", "fixed")
        with self.assertRaises(NativeAuthorityError):
            source_authority(WORKSPACE, SOURCE.parent / "rasa-other", INVENTORY, "fixed", "fixed")

    def test_ranking_rejects_truth_injection_and_invalid_limit(self):
        for value in ({"text": "hi", "ranking_length": True},
                      {"text": "hi", "ranking_length": -1},
                      {"text": "hi", "ranking_length": 2, "expected_pass": True}):
            with self.subTest(value=value), self.assertRaises(NativeAuthorityError):
                validate_input("ranking", value)

    def test_form_schema_preserves_float_type_and_rejects_extra_truth(self):
        task = next(task for task in public_catalog(CATALOG)["tasks"] if task["task_id"] == "RF02")
        self.assertEqual(task["input"]["slot_type"], "float")
        validate_input("form", task["input"])
        injected = {**task["input"], "expected_slot": 5}
        with self.assertRaises(NativeAuthorityError):
            validate_input("form", injected)

    def test_original_truncation_frame_uses_common_default_ten_and_late_classes(self):
        catalog = public_catalog(CATALOG)
        rankings = [task for task in catalog["tasks"] if task["kind"] == "ranking"]
        self.assertTrue(all(task["input"]["ranking_length"] == 10 for task in rankings))
        classes = sorted({row["intent"] for row in catalog["training_examples"]})
        self.assertGreater(len(classes), 10)
        training_labels = {row["text"]: row["intent"] for row in catalog["training_examples"]}
        for ident in ("RR01", "RR02"):
            task = next(task for task in rankings if task["task_id"] == ident)
            self.assertIn(training_labels[task["input"]["text"]], classes[10:])

    def test_duplicate_catalog_identity_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            value = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
            value["tasks"].append(deepcopy(value["tasks"][0]))
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(NativeAuthorityError):
                public_catalog(path)

    def test_single_class_training_rejected_before_native_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            value = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
            value["training_examples"] = [{"text": "hello", "intent": "greet"}]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(NativeAuthorityError):
                public_catalog(path)

    def test_docker_command_has_no_network_and_readonly_source(self):
        command = docker_command(image="rasa/rasa@sha256:" + "a" * 64,
            workspace=WORKSPACE, work_dir=WORKSPACE / "experiment/work/v9-test-only",
            source_root=SOURCE, inventory_path=INVENTORY, catalog_path=CATALOG,
            form_state="fixed", ranking_state="parent",
            expected_source_closure_sha256="b" * 64, container_name="tosem-v9-rasa-unit-only")
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("--read-only", command)
        self.assertIn("CUDA_VISIBLE_DEVICES=-1", command)
        self.assertTrue(any("target=/study,readonly" in part for part in command))
        self.assertEqual(command[command.index("--ranking-state") + 1], "parent")

    def test_unpinned_dependency_image_rejected(self):
        with self.assertRaises(NativeAuthorityError):
            docker_command(image="rasa/rasa:latest", workspace=WORKSPACE,
                work_dir=WORKSPACE / "experiment/work/v9-test-only", source_root=SOURCE,
                inventory_path=INVENTORY, catalog_path=CATALOG, form_state="fixed",
                ranking_state="fixed", expected_source_closure_sha256="b" * 64,
                container_name="tosem-v9-rasa-unit-only")


if __name__ == "__main__":
    unittest.main()

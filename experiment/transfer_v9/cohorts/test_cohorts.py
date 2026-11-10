"""Source/data checks only; no native application or model is invoked."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest

from experiment.transfer_v9 import cohorts


class CohortSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = cohorts.construct_catalogs()
        cls.plan = cohorts.construct_frames(cls.catalogs)
        cls.frame = cohorts.construct_collector_frame(cls.catalogs, cls.plan)

    def test_all_sixteen_task_identities_are_disjoint_between_cohorts(self):
        dev = {t["task_id"] for app in cohorts.APPS for t in self.catalogs["development"][app]["tasks"]}
        val = {t["task_id"] for app in cohorts.APPS for t in self.catalogs["validation"][app]["tasks"]}
        self.assertEqual(len(dev), 16)
        self.assertEqual(len(val), 16)
        self.assertFalse(dev & val)

    def test_every_vanna_development_question_and_result_differs(self):
        development = self.catalogs["development"]["vanna"]
        validation = self.catalogs["validation"]["vanna"]
        self.assertNotEqual(development["rows"], validation["rows"])
        for dev, val in zip(development["tasks"], validation["tasks"]):
            with self.subTest(task=val["task_id"]):
                self.assertNotEqual(dev["question"], val["question"])
                self.assertNotEqual(dev["expected_rows"], val["expected_rows"])
                self.assertEqual(dev["family"], val["family"])
                self.assertEqual(dev["case"], val["case"])

    def test_vanna_contracts_are_recomputed_from_source_sqlite(self):
        for cohort in cohorts.COHORTS:
            catalog = self.catalogs[cohort]["vanna"]
            independently_computed = cohorts.sqlite_references(catalog)
            self.assertEqual(len(independently_computed), 8)
            for task in catalog["tasks"]:
                self.assertEqual(task["expected_rows"], independently_computed[task["task_id"]])

    def test_rasa_input_bytes_differ_while_public_training_frame_is_shared(self):
        development = self.catalogs["development"]["rasa"]
        validation = self.catalogs["validation"]["rasa"]
        self.assertEqual(development["training_examples"], validation["training_examples"])
        classes = sorted({example["intent"] for example in validation["training_examples"]})
        self.assertEqual(len(classes), 12)
        self.assertEqual(classes[10:], ["track_parcel", "weather_forecast"])
        for dev, val in zip(development["tasks"], validation["tasks"]):
            self.assertNotEqual(dev["input"], val["input"])
            self.assertEqual(dev["kind"], val["kind"])
            if dev["kind"] == "ranking":
                self.assertEqual(dev["input"]["ranking_length"], 10)
                self.assertEqual(val["input"]["ranking_length"], 10)
                self.assertEqual(dev["contract"]["ranking_length"], 10)

    def test_vanna_public_projection_excludes_all_reference_fields(self):
        for cohort in cohorts.COHORTS:
            catalog = self.catalogs[cohort]["vanna"]
            data, tasks = cohorts._public_vanna(catalog)
            self.assertEqual(set(data), {"schema", "rows"})
            self.assertEqual(set(tasks), {"tasks"})
            for task in tasks["tasks"]:
                self.assertEqual(set(task), {"task_id", "family", "question"})

    def test_rasa_public_projection_excludes_contracts_and_provenance(self):
        for cohort in cohorts.COHORTS:
            catalog = self.catalogs[cohort]["rasa"]
            public = cohorts._public_rasa(catalog)
            self.assertEqual(set(public), {"application_id", "training_examples", "tasks"})
            for task in public["tasks"]:
                self.assertEqual(set(task), {"task_id", "kind", "input"})

    def test_public_projections_cannot_mutate_private_catalog(self):
        catalog = copy.deepcopy(self.catalogs["validation"]["vanna"])
        source_rows = copy.deepcopy(catalog["rows"])
        data, tasks = cohorts._public_vanna(catalog)
        data["rows"][0][2] = -999
        tasks["tasks"][0]["question"] = "modified software fixture"
        self.assertEqual(catalog["rows"], source_rows)
        self.assertNotEqual(catalog["tasks"][0]["question"], tasks["tasks"][0]["question"])

    def test_development_contains_healthy_eight_and_balanced_bad_groups(self):
        for app, rows in self.frame["development"].items():
            self.assertEqual(len(rows), 16)
            for state, expected_count in (("H", 8), ("A", 4), ("B", 4)):
                selected = [row for row in rows if row["state"] == state]
                self.assertEqual(len(selected), expected_count)
                self.assertEqual(sum(row["required_contract_pass"] for row in selected), 8 if state == "H" else 2)
                self.assertTrue(all(row["frame_role"] == "development" for row in selected))

    def test_full_validation_and_confirmation_execute_every_case_state_task(self):
        for app, rows in self.frame["validation"].items():
            self.assertEqual(len(rows), 128)
            primary = [row for row in rows if row["frame_role"] == "primary_bank"]
            confirm = [row for row in rows if row["frame_role"] == "fresh_confirmation"]
            self.assertEqual(len(primary), 96)
            self.assertEqual(len(confirm), 32)
            expected_ids = {t["task_id"] for t in self.catalogs["validation"][app]["tasks"]}
            for pass_index in range(4):
                groups = {}
                for row in rows:
                    if row["pass_index"] == pass_index:
                        groups.setdefault((row["case_id"], row["state"]), []).append(row["task_id"])
                self.assertEqual(len(groups), 4)
                self.assertTrue(all(set(task_ids) == expected_ids and len(task_ids) == 8 for task_ids in groups.values()))

    def test_operation_ids_never_repeat_and_counts_do_not_create_defects(self):
        all_rows = [row for phase in ("development", "validation") for app in cohorts.APPS for row in self.frame[phase][app]]
        self.assertEqual(len(all_rows), 288)
        self.assertEqual(len({row["operation_id"] for row in all_rows}), 288)
        self.assertEqual(self.plan["totals"]["independent_upstream_cases"], 4)
        self.assertEqual(self.plan["totals"]["core_native_requests"], 288)
        self.assertEqual(self.plan["totals"]["anticipated_vanna_chat_requests_if_one_sql_and_one_plot_call"], 180)
        self.assertEqual(self.plan["totals"]["vanna_chat_upper_bound_at_three_per_native_request"], 432)

    def test_generated_bytes_match_manifest(self):
        manifest = json.loads((cohorts.DATA / "COHORT_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 12)
        for relative, binding in manifest["files"].items():
            data = (cohorts.HERE / relative).read_bytes()
            self.assertEqual(len(data), binding["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), binding["sha256"])


if __name__ == "__main__":
    unittest.main()

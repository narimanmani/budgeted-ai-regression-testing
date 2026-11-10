"""Prospective live-plan arithmetic/provenance checks; no application execution."""
from __future__ import annotations

import hashlib
import json
import unittest

from experiment.transfer_v9.common import HERE, ROOT


class LiveConfirmationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((HERE / "cohorts/LIVE_CONFIRMATION_PLAN.json").read_text(encoding="utf-8"))

    def test_original_288_frame_and_manifest_remain_byte_identical(self):
        base = self.plan["base_frame"]
        for key, hash_key in (("path", "sha256"), ("manifest_path", "manifest_sha256")):
            self.assertEqual(hashlib.sha256((ROOT / base[key]).read_bytes()).hexdigest(), base[hash_key])
        self.assertEqual(base["planned_native_requests_unchanged"], 288)
        self.assertFalse(base["original_frame_and_manifest_modified"])

    def test_live_plan_fits_existing_combined_and_split_request_envelopes(self):
        total = self.plan["accounting"]
        cg1 = self.plan["methods"]["CG1"]
        full = self.plan["methods"]["budgeted_retest_all"]
        self.assertEqual(cg1["profiles"]["native_requests"], 8 * 3)
        self.assertEqual(cg1["pairs"]["maximum_native_requests"], 2 * 2)
        self.assertEqual(cg1["maximum_native_requests_per_setting"], 24 + 4)
        self.assertEqual(full["maximum_native_requests_per_setting"], 8 * 2)
        self.assertEqual(total["additional_native_request_ceiling"], (28 + 16) * 2)
        self.assertEqual(total["complete_plan_native_request_ceiling"], 288 + 88)
        self.assertEqual(total["complete_plan_generative_native_request_ceiling"], 144 + 44)
        self.assertEqual(total["complete_plan_queryfree_native_request_ceiling"], 144 + 44)
        self.assertLessEqual(total["complete_plan_native_request_ceiling"], 400)
        self.assertLessEqual(total["complete_plan_generative_native_request_ceiling"], 200)
        self.assertLessEqual(total["complete_plan_queryfree_native_request_ceiling"], 200)
        self.assertEqual(total["combined_contingency_native_requests"], 400 - 376)
        self.assertEqual(total["complete_plan_provider_chat_upper_bound_at_three_per_vanna_request"], 188 * 3)
        self.assertLessEqual(total["complete_plan_provider_chat_upper_bound_at_three_per_vanna_request"], 600)

    def test_case_a_and_complete_public_task_catalogs_match_registered_sources(self):
        inventory = json.loads((HERE / "screening/CASE_INVENTORY.json").read_text(encoding="utf-8"))
        cases = {case["case_id"] for case in inventory["case_candidates"]}
        self.assertEqual(self.plan["setting_order"], ["vanna", "rasa"])
        self.assertEqual(self.plan["method_order"], ["CG1", "budgeted_retest_all"])
        for setting, data in self.plan["settings"].items():
            self.assertIn(data["case_id"], cases)
            self.assertEqual(data["case_id"], "VANNA_SQL_WITHIN" if setting == "vanna" else "RASA_FORM_TRIGGER")
            public = json.loads((ROOT / data["public_task_path"]).read_text(encoding="utf-8"))
            self.assertEqual(data["task_ids"], [task["task_id"] for task in public["tasks"]])
            self.assertEqual(len(data["task_ids"]), 8)

    def test_matched_total_ceiling_does_not_artificially_limit_full_retesting(self):
        self.assertEqual(self.plan["fixed_conditions"]["whole_native_request_ceiling_per_arm"], 28)
        cg1 = self.plan["methods"]["CG1"]
        full = self.plan["methods"]["budgeted_retest_all"]
        self.assertTrue(cg1["selection"]["pair_limit_is_derived_from_remaining_total_budget"])
        self.assertFalse(cg1["selection"]["additional_artificial_K_ceiling"])
        self.assertEqual((28 - cg1["profiles"]["native_requests"]) // 2, 2)
        self.assertFalse(full["pairs"]["additional_artificial_K_ceiling"])
        self.assertEqual(full["whole_native_request_ceiling_per_setting"], 28)
        self.assertEqual(full["unused_allowance_if_all_eight_pairs_complete"], 12)

    def test_all_possible_operation_identities_are_unique_and_public(self):
        ids = []
        for setting, data in self.plan["settings"].items():
            profile = self.plan["methods"]["CG1"]["profiles"]
            for sample_index in range(3):
                for task_id in data["task_ids"]:
                    ids.append(profile["operation_id_template"].format(setting=setting, sample_index=sample_index, task_id=task_id))
            for method in self.plan["method_order"]:
                template = self.plan["methods"][method]["pairs"]["operation_id_template"]
                for task_id in data["task_ids"]:
                    for endpoint in ("old", "new"):
                        ids.append(template.format(setting=setting, task_id=task_id, endpoint=endpoint))
        # The identity catalog includes all potential CG1 selected tasks. Only
        # two pairs per setting may be dispatched; these are not extra calls.
        self.assertEqual(len(ids), 112)
        self.assertEqual(len(set(ids)), 112)
        self.assertTrue(all(ident.startswith("live-") for ident in ids))

    def test_new_plan_cannot_substitute_bank_answers_or_seed_free_history(self):
        conditions = self.plan["fixed_conditions"]
        self.assertEqual(conditions["initial_history"], "empty")
        self.assertEqual(conditions["operational_checker"], "contract_exact")
        for key in ("recorded_bank_outputs_may_replace_live_requests", "profile_verdicts_may_become_paired_history",
                    "current_or_future_truth_may_influence_selection", "reference_bank_failure_labels_may_influence_selection"):
            self.assertFalse(conditions[key])
        self.assertTrue(self.plan["freeze_and_stop"]["must_be_in_root_study_freeze_before_first_development_output"])
        self.assertFalse(self.plan["freeze_and_stop"]["conditional_on_positive_replay_gain"])


if __name__ == "__main__":
    unittest.main()

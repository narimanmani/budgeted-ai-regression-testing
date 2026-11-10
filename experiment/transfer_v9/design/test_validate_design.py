"""Admission tests target leakage, cost omission and invalid claim boundaries."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("v9_validate_design", HERE / "validate_design.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def complete_structural_fixture():
    """Synthetic structural fixture; never used as experimental evidence."""
    p = json.loads((HERE / "protocol.template.json").read_text(encoding="utf-8"))
    r = {"settings": [], "cases": [], "freeze": {
        "sealed_before_native_validation_outputs": True,
        "all_required_bytes_available": True, "no_validation_policy_scores_seen": True,
        "manifest_sha256": "d" * 64}}
    for app_index, sid in enumerate(("unseen_a", "unseen_b")):
        tasks = [f"{sid}_{i}" for i in range(8)]
        r["settings"].append({"setting_id": sid, "native_boundary": "native_component",
                              "previously_used_for_guidance_development": False,
                              "validation_task_ids": tasks})
        for case_index in range(2):
            cid = f"{sid}_case{case_index}"
            r["cases"].append({
                "case_id": cid, "setting_id": sid,
                "upstream_repository_url": "https://example.invalid/upstream",
                "upstream_change_url": "https://example.invalid/commit",
                "buggy_commit": "a" * 40, "fixed_commit": "b" * 40,
                "fix_parent_commit": "a" * 40, "mechanism_id": f"mechanism{case_index}",
                "case_origin": "upstream_historical_bugfix",
                "intervention_direction": "controlled_reintroduction",
                "production_path": "production/example.py", "entry_point": "Application.invoke",
                "upstream_contract_evidence": "upstream/tests/test_example.py",
                "contract_sha256": "c" * 64, "source_manifest_sha256": "d" * 64,
                "contract_path": f"test-fixture/{cid}/contract.json",
                "source_manifest_path": f"test-fixture/{cid}/sources.json",
                "validation_task_ids": tasks, "selection_used_policy_scores": False,
                "license_path": "LICENSE"})
    return p, r


class AdmissionTests(unittest.TestCase):
    def test_planned_native_requests_not_replay_trajectories(self):
        p, r = complete_structural_fixture()
        out = MODULE.validate_design(p, r)
        self.assertEqual(out["status"], "PASS_STRUCTURAL_ADMISSION", out["errors"])
        self.assertEqual(out["planned_counts"]["native_bank_request_plan"], 256)
        self.assertEqual(out["planned_counts"]["native_live_policy_confirmation_ceiling"], 88)
        self.assertEqual(out["planned_counts"]["native_core_request_plan"], 344)
        self.assertEqual(out["planned_counts"]["native_total_registered_request_ceiling"], 376)
        self.assertEqual(out["planned_counts"]["native_contingency_requests"], 24)
        self.assertEqual(out["planned_counts"]["counterfactual_trajectories"], 672)
        self.assertEqual(out["planned_counts"]["counterfactual_decisions"], 10752)
        self.assertFalse(out["claims_permitted"]["complete_application_level_external_validation_established"])
        self.assertFalse(out["claims_permitted"]["portable_guidance_established"])

    def test_empty_registry_cannot_be_run_ready(self):
        p, _ = complete_structural_fixture()
        r = json.loads((HERE / "registry.template.json").read_text(encoding="utf-8"))
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_future_truth_and_foreign_history_are_rejected(self):
        for field in ("current_or_future_truth_to_selector", "reference_outcomes_to_selector",
                      "operational_error_mask_depends_on_truth", "impact_omission_depends_on_current_fault_outcomes"):
            p, r = complete_structural_fixture()
            p["replay"][field] = True
            self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED", field)
        p, r = complete_structural_fixture()
        p["replay"]["history_source"] = "all_reference_pairs"
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_free_profile_and_cross_state_reuse_are_rejected(self):
        for field, bad in (("profile_cost_charged_only_to_consuming_method", False),
                           ("profile_reuse_across_distinct_states", True),
                           ("profile_old_requests_per_task_state", 1)):
            p, r = complete_structural_fixture()
            p["costs"][field] = bad
            self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED", field)

    def test_legacy_campaign_cannot_be_reset_or_extended(self):
        for field, bad in (("closed_native_count", 0), ("closed_native_cap", 10000),
                           ("reset_or_increase_legacy_caps", True)):
            p, r = complete_structural_fixture()
            p["legacy"][field] = bad
            self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED", field)

    def test_undeclared_llm_extension_and_unfunded_native_plan_are_rejected(self):
        for field, bad in (("new_llm_generation_request_cap", 1), ("native_component_request_cap", 255)):
            p, r = complete_structural_fixture()
            p["new_phase_resources"][field] = bad
            self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED", field)

    def test_a_previous_application_is_not_an_untouched_case(self):
        p, r = complete_structural_fixture()
        r["settings"][0]["setting_id"] = "Open-WebUI"
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_one_mechanism_copied_twice_is_not_independence(self):
        p, r = complete_structural_fixture()
        r["cases"][1]["mechanism_id"] = r["cases"][0]["mechanism_id"]
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_score_selection_and_natural_regression_mislabel_are_rejected(self):
        p, r = complete_structural_fixture()
        r["cases"][0]["selection_used_policy_scores"] = True
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")
        p, r = complete_structural_fixture()
        r["cases"][0]["intervention_direction"] = "natural_chronological_change"
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_byte_verification_does_not_accept_digest_only_declarations(self):
        p, r = complete_structural_fixture()
        out = MODULE.validate_design(p, r, workspace=HERE, verify_bytes=True)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertTrue(any("Frozen byte binding failed" in msg for msg in out["errors"]))

    def test_win_based_stopping_is_rejected(self):
        p, r = complete_structural_fixture()
        p["analysis"]["stop_on_winning_result"] = True
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_boolean_cannot_be_a_count(self):
        p, r = complete_structural_fixture()
        p["native_bank"]["passes_per_cell"] = True
        self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED")

    def test_live_confirmation_cannot_borrow_bank_or_hide_profile_cost(self):
        for key, bad in (("bank_outcomes_reused_as_execution", True),
                         ("cg1_profile_requests_per_cell", 0),
                         ("source_case_choice_uses_policy_scores", True)):
            p, r = complete_structural_fixture()
            p["native_policy_confirmation"][key] = bad
            self.assertEqual(MODULE.validate_design(p, r)["status"], "BLOCKED", key)


if __name__ == "__main__":
    unittest.main()

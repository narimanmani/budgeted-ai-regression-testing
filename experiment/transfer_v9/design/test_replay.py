"""Pure synthetic tests for replay invariants; none are empirical observations."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("v9_replay", HERE / "replay.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def fixture():
    protocol = json.loads((HERE / "protocol.template.json").read_text(encoding="utf-8"))
    tasks = [f"T{i}" for i in range(8)]
    bank = {"schema_version": "v9-native-bank-1", "settings": [], "records": []}
    for sid in ("synthetic_a", "synthetic_b"):
        setting = {"setting_id": sid, "task_ids": tasks,
                   "case_ids": {"A": sid + "_case_a", "B": sid + "_case_b"},
                   "states": {state: {"state_digest": R.digest([sid, state]),
                              "changed_tokens": [] if state == "H" else [f"code:production/{state}/handler"]}
                              for state in ("H", "A", "B")}}
        bank["settings"].append(setting)
        for case in ("A", "B"):
            for state in ("H", case):
                for i, task in enumerate(tasks):
                    affected = i < 2 if case == "A" else 2 <= i < 4
                    for p in range(3):
                        rid = f"{sid}:{case}:{state}:{task}:{p}"
                        dependencies = (["code:production/A/handler"] if i < 2 else
                                        ["code:production/B/handler"] if i < 4 else ["code:production/control/handler"])
                        bank["records"].append({"record_id": rid, "setting_id": sid,
                            "case_id": setting["case_ids"][case], "state": state,
                            "task_id": task, "pass_index": p,
                            "contract_pass": not (state != "H" and affected),
                            "elapsed_seconds": 0.01 + i / 1000 + p / 10000,
                            "checker_seconds": 0.0001, "feature_seconds": 0.0002,
                            "observed_dependency_tokens": dependencies,
                            "raw_sha256": R.digest([rid, "raw"]), "receipt_sha256": R.digest([rid, "receipt"])})
    return bank, protocol


class ReplayInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = R.load_guidance()

    def run_one(self, bank_data=None, protocol=None, **kwargs):
        b, p = fixture()
        b = bank_data if bank_data is not None else b
        p = protocol if protocol is not None else p
        index = R.BankIndex(b, self.guide)
        defaults = {"setting_id": "synthetic_a", "sequence_order": "recurrence_blocked",
                    "native_pass": 0, "impact_level": "observed_native_edges",
                    "checker_level": "contract_exact", "request_budget": 256,
                    "method": "CG1", "horizon": 16}
        defaults.update(kwargs)
        return R.run_trajectory(index, p, self.guide, **defaults)

    def test_current_and_future_reference_truth_cannot_change_first_decision(self):
        bank, protocol = fixture()
        original = self.run_one(bank, protocol)
        changed = copy.deepcopy(bank)
        for row in changed["records"]:
            row["contract_pass"] = not row["contract_pass"]
        perturbed = self.run_one(changed, protocol)
        self.assertEqual(original["episodes"][0]["predecision"], perturbed["episodes"][0]["predecision"])
        self.assertNotEqual(original["metrics"], perturbed["metrics"])

    def test_unvisited_new_family_cannot_change_earlier_decisions(self):
        bank, protocol = fixture()
        original = self.run_one(bank, protocol)
        changed = copy.deepcopy(bank)
        for row in changed["records"]:
            if row["state"] == "B":
                row["contract_pass"] = not row["contract_pass"]
        perturbed = self.run_one(changed, protocol)
        for i in range(9):
            self.assertEqual(original["episodes"][i]["predecision"], perturbed["episodes"][i]["predecision"])

    def test_all_methods_pay_profiles_only_if_consumed_and_never_exceed_budget(self):
        for method in R.METHODS:
            for budget in (128, 256):
                tr = self.run_one(method=method, request_budget=budget)
                costs = tr["final_costs"]
                self.assertLessEqual(costs["profile_requests"] + costs["selected_requests"], budget)
                if method in R.PROFILE_METHODS:
                    self.assertEqual(costs["profile_requests"], 72)
                    self.assertGreater(costs["profile_native_seconds"], 0)
                else:
                    self.assertEqual(costs["profile_requests"], 0)
                    self.assertEqual(costs["profile_native_seconds"], 0)

    def test_identical_state_profile_is_reused_and_not_free_across_new_states(self):
        tr = self.run_one()
        acquisitions = [row["acquisition"] for row in tr["episodes"] if row["acquisition"]]
        self.assertEqual([x["old_state"] for x in acquisitions], ["H", "A", "B"])
        self.assertTrue(all(x["requests"] == 24 for x in acquisitions))
        self.assertEqual(len({x["profile_key"] for x in acquisitions}), 3)

    def test_insufficient_acquisition_budget_does_not_borrow_research_bank_for_free(self):
        tr = self.run_one(request_budget=16)
        self.assertTrue(all(row["acquisition_denied"] for row in tr["episodes"]))
        self.assertTrue(all(not row["selected_pairs"] for row in tr["episodes"]))
        self.assertEqual(tr["final_costs"]["profile_requests"], 0)
        self.assertGreater(tr["metrics"]["totals"]["missed_reference_regressions"], 0)

    def test_full_retest_is_complete_only_when_the_shared_budget_can_afford_it(self):
        full = self.run_one(method="budgeted_retest_all", request_budget=256)
        partial = self.run_one(method="budgeted_retest_all", request_budget=128)
        self.assertEqual(full["final_costs"]["selected_requests"], 256)
        self.assertTrue(all(len(row["selected_pairs"]) == 8 for row in full["episodes"]))
        self.assertEqual(partial["final_costs"]["selected_requests"], 128)
        self.assertTrue(all(len(row["selected_pairs"]) == 4 for row in partial["episodes"]))

    def test_noise_masks_are_coupled_between_methods_and_independent_of_truth(self):
        bank, protocol = fixture()
        tr = self.run_one(bank, protocol, method="budgeted_retest_all", checker_level="seeded_symmetric_flip_p25")
        changed = copy.deepcopy(bank)
        for row in changed["records"]:
            row["contract_pass"] = not row["contract_pass"]
        other = self.run_one(changed, protocol, method="budgeted_retest_all", checker_level="seeded_symmetric_flip_p25")
        masks = lambda result: [[(pair["receipt"]["old_mask_flipped"], pair["receipt"]["new_mask_flipped"])
                                 for pair in row["selected_pairs"]] for row in result["episodes"]]
        self.assertEqual(masks(tr), masks(other))
        self.assertGreater(tr["metrics"]["totals"]["controlled_endpoint_flips"], 0)

    def test_operational_history_is_owned_selected_and_strictly_earlier(self):
        tr = self.run_one(checker_level="seeded_symmetric_flip_p25")
        previous = []
        for row in tr["episodes"]:
            self.guide.checked_history(previous, [f"T{i}" for i in range(8)], tr["trajectory_id"], row["episode_index"])
            for pair in row["selected_pairs"]:
                event = pair["history_event"]
                self.assertEqual(event["trajectory_id"], tr["trajectory_id"])
                self.assertEqual(event["old_primary_pass"], pair["receipt"]["old_operational_pass"])
                self.assertEqual(event["new_primary_pass"], pair["receipt"]["new_operational_pass"])
                previous.append(event)

    def test_profile_feature_boundary_excludes_all_reference_answers(self):
        bank, _ = fixture()
        index = R.BankIndex(bank, self.guide)
        public = index.profile_observations("synthetic_a", "H")
        for samples in public.values():
            for sample in samples:
                self.assertNotIn("contract_pass", sample)
                self.assertNotIn("raw_output", sample)
        self.assertNotIn("bank", R.select_policy.__annotations__)

    def test_missing_native_cell_blocks_complete_factorial(self):
        bank, _ = fixture()
        bank["records"].pop()
        with self.assertRaises(R.ReplayProtocolError):
            R.BankIndex(bank, self.guide)

    def test_mutated_guidance_bytes_are_rejected_before_import(self):
        original = Path(__file__).resolve().parents[3] / "experiment/validation_v7/guidance/policy.py"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.py"
            path.write_bytes(original.read_bytes() + b"\n")
            with self.assertRaises(R.ReplayProtocolError):
                R.load_guidance(path)

    def test_full_frame_counts_are_replay_not_native_calls(self):
        bank, protocol = fixture()
        result = R.run_factorial(bank, protocol, self.guide)
        summary = result["summary"]
        self.assertEqual(summary["physical_primary_native_records"], 192)
        self.assertEqual(summary["primary_counterfactual_trajectories"], 672)
        self.assertEqual(summary["secondary_amortization_counterfactual_trajectories"], 1344)
        self.assertEqual(summary["all_counterfactual_decisions"], 18816)
        self.assertEqual(summary["new_native_or_model_dispatches_in_replay"], 0)
        self.assertFalse(summary["portable_guidance_or_tosem_readiness_established"])

    def test_setup_is_charged_once_and_exclusive_wall_components_reconcile(self):
        bank, protocol = fixture()
        bank["settings"][0]["common_setup_seconds"] = 17.5
        for method in ("CG1", "budgeted_retest_all"):
            result = self.run_one(bank, protocol, method=method)
            costs = result["final_costs"]
            self.assertEqual(costs["common_setup_seconds"], 17.5)
            self.assertAlmostEqual(costs["total_allocated_wall_seconds"], sum(costs[key] for key in (
                "profile_native_seconds", "selected_native_seconds", "feature_seconds", "checker_seconds", "common_setup_seconds")))
            self.assertAlmostEqual(costs["total_allocated_native_wall_plus_controller_cpu_proxy_seconds"],
                costs["total_allocated_wall_seconds"] + costs["decision_cpu_seconds"] + costs["operational_mask_cpu_seconds"])
            self.assertGreaterEqual(costs["decision_cpu_seconds"], 0)
            self.assertGreaterEqual(costs["operational_mask_cpu_seconds"], 0)

    def test_same_recorded_world_reanalysis_keeps_outcomes_selections_and_native_costs_deterministic(self):
        first = self.run_one(checker_level="seeded_symmetric_flip_p25")
        second = self.run_one(checker_level="seeded_symmetric_flip_p25")
        self.assertEqual(first["metrics"], second["metrics"])
        for left, right in zip(first["episodes"], second["episodes"]):
            self.assertEqual(left["predecision"], right["predecision"])
            self.assertEqual(left["selected_pairs"], right["selected_pairs"])
        for key in first["final_costs"]:
            if key not in ("decision_cpu_seconds", "operational_mask_cpu_seconds",
                            "total_allocated_native_wall_plus_controller_cpu_proxy_seconds"):
                self.assertEqual(first["final_costs"][key], second["final_costs"][key])

    def test_fresh_confirmation_retains_disagreement_without_relabeling(self):
        bank, _ = fixture()
        original = copy.deepcopy(bank)
        confirmation = {"schema_version": "v9-native-bank-1", "settings": copy.deepcopy(bank["settings"]), "records": []}
        for record in bank["records"]:
            if record["pass_index"] != 0:
                continue
            fresh = copy.deepcopy(record)
            fresh["pass_index"] = 3
            fresh["record_id"] += ":fresh"
            fresh["receipt_sha256"] = R.digest([fresh["record_id"], "fresh-operation"])
            confirmation["records"].append(fresh)
        confirmation["records"][0]["contract_pass"] = not confirmation["records"][0]["contract_pass"]
        result = R.compare_confirmation(bank, confirmation, self.guide)
        self.assertEqual(result["fresh_confirmation_records"], 64)
        self.assertEqual(len(result["disagreements_retained"]), 1)
        self.assertFalse(result["primary_or_reference_labels_replaced"])
        self.assertEqual(bank, original)

    def test_checker_moderation_uses_the_registered_difference_in_differences(self):
        from collections import Counter
        matched = {}
        for checker, values in (("contract_exact", [10, 12, 13, 15]),
                                ("seeded_symmetric_flip_p25", [6, 8, 8, 7])):
            methods = {}
            for method, score in zip(("cost_only", "impact_only", "history_only", "always_combined"), values):
                methods[method] = {"identity": {"setting_id": "fixture", "checker_level": checker, "method": method},
                                   "totals": Counter({"detected_true_regressions": score, "reference_discordant_alarms": 0}),
                                   "costs": Counter({"profile_requests": 24, "selected_requests": 16})}
            matched[checker] = methods
        contrasts, moderation = R.fixed_arm_contrasts(matched)
        self.assertEqual(len(contrasts), 2)
        self.assertEqual(moderation[0]["noisy_minus_exact_I_by_H_contrast"]["detected_true_regressions"], -3)

    def test_confirmation_rejects_duplicated_fresh_operation_ids_and_receipts(self):
        bank, _ = fixture()
        rows = []
        for row in bank["records"]:
            if row["pass_index"] == 0:
                fresh = copy.deepcopy(row)
                fresh["pass_index"] = 3
                fresh["record_id"] += ":fresh"
                fresh["receipt_sha256"] = R.digest([fresh["record_id"], "fresh-operation"])
                rows.append(fresh)
        for field in ("record_id", "receipt_sha256"):
            changed = copy.deepcopy(rows)
            changed[1][field] = changed[0][field]
            confirmation = {"settings": copy.deepcopy(bank["settings"]), "records": changed}
            with self.assertRaises(R.ReplayProtocolError):
                R.compare_confirmation(bank, confirmation, self.guide)


if __name__ == "__main__":
    unittest.main()

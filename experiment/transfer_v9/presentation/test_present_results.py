"""Synthetic software checks only; no native study outcomes are read."""
import copy
import importlib.util
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("v9_presentation", HERE / "present_results.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def fixture():
    summary = {"status": "COMPLETE_RECORDED_OUTCOME_REPLAY", "matched_cells": [],
        "cg1_comparisons": [], "fixed_arm_impact_by_history_contrasts": [],
        "checker_moderation_of_fixed_arm_impact_by_history": [],
        "primary_counterfactual_trajectories": 672,
        "secondary_amortization_counterfactual_trajectories": 1344,
        "physical_primary_native_records": 192,
        "independently_sourced_upstream_cases": ["synthetic_a_A", "synthetic_a_B", "synthetic_b_A", "synthetic_b_B"],
        "factor_coverage": {"fixture_not_empirical": True}}
    groups = []
    for horizon, setting, order, impact, checker, per_episode in itertools.product(
            (4, 8, 16), ("synthetic_a", "synthetic_b"),
            ("recurrence_blocked", "mechanism_interleaved"),
            ("observed_native_edges", "seeded_edge_omission"),
            ("contract_exact", "seeded_symmetric_flip_p25"), (8, 16)):
        base = {"analysis_frame": "primary" if horizon == 16 else "secondary_amortization",
                "horizon": horizon, "setting_id": setting, "sequence_order": order,
                "impact_level": impact, "checker_level": checker,
                "request_budget": horizon * per_episode}
        groups.append(base)
        for method in P.METHOD_ORDER:
            profiled = method not in ("seeded_random", "budgeted_retest_all")
            requests = min(horizon * per_episode, 24 + horizon * 4) if profiled else horizon * per_episode
            profiles = 24 if profiled else 0
            costs = {"profile_requests": profiles * 3, "selected_requests": (requests - profiles) * 3,
                     "total_allocated_wall_seconds": requests * 0.1 * 3,
                     "decision_cpu_seconds": 0.001 * 3, "operational_mask_cpu_seconds": 0.0001 * 3,
                     "total_allocated_native_wall_plus_controller_cpu_proxy_seconds": (requests * 0.1 + 0.0011) * 3}
            detections = horizon * 3 if method in ("CG1", "budgeted_retest_all") else horizon * 3 - 3
            summary["matched_cells"].append({"identity": {**base, "method": method}, "native_passes": [0, 1, 2],
                "totals": {"reference_regression_opportunities": horizon * 3,
                           "detected_true_regressions": detections,
                           "missed_reference_regressions": horizon * 3 - detections,
                           "reference_discordant_alarms": 0, "repair_alarms": 0,
                           "controlled_endpoint_flips": 0, "endpoint_judgments": (requests-profiles) * 3},
                "costs": costs})
    for base in groups:
        for baseline in P.METHOD_ORDER:
            if baseline != "CG1":
                summary["cg1_comparisons"].append({"identity": base, "baseline": baseline,
                    "cg1_minus_baseline_detections": 0 if baseline == "budgeted_retest_all" else 3,
                    "cg1_minus_baseline_discordant_alarms": 0, "cg1_minus_baseline_allocated_requests": -12,
                    "by_upstream_case": {base["setting_id"] + "_A": {"detection_delta": 0, "discordant_alarm_delta": 0},
                                         base["setting_id"] + "_B": {"detection_delta": 3, "discordant_alarm_delta": 0}}})
    live = {"schema": "v9-live-policy-confirmation-1", "cells_planned": 4,
            "matched_native_request_ceiling_per_cell": 28, "long_history_or_noisy_checker_live_claimed": False,
            "cells": []}
    for setting, method in itertools.product(("synthetic_a", "synthetic_b"), ("CG1", "budgeted_retest_all")):
        profiles, selected = (24, 4) if method == "CG1" else (0, 16)
        live["cells"].append({"setting_id": setting, "method": method, "case_id": setting + "_A",
            "physically_executed_not_counterfactual_replay": True, "initial_history": "empty",
            "native_request_ceiling": 28, "operational_checker": "exact frozen contract",
            "actual_profile_native_requests": profiles, "actual_selected_native_requests": selected,
            "actual_total_native_requests": profiles + selected,
            "unused_native_request_allowance": 28-profiles-selected,
            "observed_contract_regression_pairs": 2, "selected_task_ids": ["synthetic_T0", "synthetic_T1"],
            "allocated_native_and_checker_feature_wall_seconds": (profiles + selected) * 0.1,
            "controller_cpu_seconds": 0.0001})
    resource = {"status": "synthetic_resource_fixture", "totals": {"native_query_units": 188,
        "queryfree_native_check_units": 188}, "private": {"api_key": "SYNTHETIC_SECRET_MUST_NOT_EXPORT"}}
    return summary, live, resource


def write_closed_fixture(root):
    run = root / "run"
    (run / "evaluation").mkdir(parents=True)
    audit_path, ready_path = run / "audit.json", run / "ANALYSIS_READINESS.json"
    summary, live, resource = fixture()
    bank, protocol = run / "NATIVE_BANK.json", run / "PROTOCOL.json"
    bank.write_text('{"fixture_only":true}', encoding="utf-8")
    protocol.write_text('{"fixture_only":true}', encoding="utf-8")
    summary["bank_sha256"], summary["protocol_sha256"] = P.sha(bank), P.sha(protocol)
    paths = {run / "evaluation/SUMMARY.json": summary,
             run / "LIVE_POLICY_CONFIRMATION.json": live,
             run / "VALIDATION_RESOURCE_SUMMARY.json": resource}
    for path, value in paths.items():
        path.write_text(json.dumps(value), encoding="utf-8")
    audited = {str(path.relative_to(root)).replace("\\", "/"): P.sha(path)
               for path in (bank, protocol, run / "LIVE_POLICY_CONFIRMATION.json", run / "VALIDATION_RESOURCE_SUMMARY.json")}
    audit = {"status": "PASS_COMPLETED_STAGE_INTEGRITY", "stage": "validation",
             "complete_registered_frame": True, "native_or_provider_dispatches_during_audit": 0,
             "evidence_bindings": audited}
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    all_paths = [*paths, bank, protocol, audit_path]
    ready = {"status": "PASS", "all_owned_helpers_closed": True,
             "bound_files_sha256": {str(path.relative_to(root)).replace("\\", "/"): P.sha(path) for path in all_paths}}
    ready_path.write_text(json.dumps(ready), encoding="utf-8")
    return run, audit_path, ready_path


class PresentationChecks(unittest.TestCase):
    def test_failed_audit_blocks_before_any_empirical_input_is_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            audit.write_text('{"status":"AUDIT_FAILED"}', encoding="utf-8")
            with mock.patch.object(P, "read_json", wraps=P.read_json) as reader:
                with self.assertRaises(P.PresentationError):
                    P.closed_input_gate(workspace=root, run=root / "nonexistent-data", audit=audit, readiness=root / "not-opened.json")
            self.assertEqual([call.args[0] for call in reader.call_args_list], [audit])

    def test_unclosed_helpers_and_missing_bindings_block_result_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, audit, ready = write_closed_fixture(root)
            obj = P.read_json(ready)
            obj["all_owned_helpers_closed"] = False
            ready.write_text(json.dumps(obj), encoding="utf-8")
            with mock.patch.object(P, "read_json", wraps=P.read_json) as reader:
                with self.assertRaises(P.PresentationError):
                    P.closed_input_gate(workspace=root, run=run, audit=audit, readiness=ready)
            self.assertEqual(len(reader.call_args_list), 2)

    def test_changed_closed_bytes_and_wrong_derivation_bindings_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, audit, ready = write_closed_fixture(root)
            (run / "LIVE_POLICY_CONFIRMATION.json").write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaises(P.PresentationError):
                P.closed_input_gate(workspace=root, run=run, audit=audit, readiness=ready)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, audit, ready = write_closed_fixture(root)
            summary_path = run / "evaluation/SUMMARY.json"
            summary = P.read_json(summary_path)
            summary["bank_sha256"] = "0" * 64
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            obj = P.read_json(ready)
            obj["bound_files_sha256"]["run/evaluation/SUMMARY.json"] = P.sha(summary_path)
            ready.write_text(json.dumps(obj), encoding="utf-8")
            with self.assertRaises(P.PresentationError):
                P.closed_input_gate(workspace=root, run=run, audit=audit, readiness=ready)

    def test_tables_keep_balanced_and_composition_confounded_horizons_separate(self):
        summary, live, resource = fixture()
        tables = P.make_tables(summary, live, resource)
        self.assertEqual(len(tables["PRIMARY_MATCHED_CELLS.csv"]), 224)
        self.assertEqual(len(tables["CG1_PRIMARY_COMPARISONS.csv"]), 192)
        self.assertTrue(all(row["horizon_composition"] == "balanced_two_cases"
                            for row in tables["BALANCED_INTERLEAVED_AMORTIZATION.csv"]))
        self.assertEqual({row["horizon_composition"] for row in tables["BLOCKED_PREFIX_COMPOSITION_CONFOUNDED_DESCRIPTIVE.csv"]}, {"A_only", "A_and_B"})
        self.assertFalse(any("SYNTHETIC_SECRET" in str(row) for row in tables["RESOURCE_SUMMARY_FIELDS.csv"]))

    def test_live_counts_do_not_borrow_a_recall_denominator_or_hide_profile_costs(self):
        _, live, _ = fixture()
        rows = P.live_rows(live)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["recall_denominator_borrowed_from_other_cell"] is False for row in rows))
        self.assertEqual(sorted(row["actual_profile_native_requests"] for row in rows), [0, 0, 24, 24])
        live["cells"][0]["actual_total_native_requests"] = 4
        with self.assertRaises(P.PresentationError):
            P.live_rows(live)

    def test_zero_reference_opportunities_remain_undefined_not_zero_recall(self):
        summary, _, _ = fixture()
        summary["matched_cells"][0]["totals"]["reference_regression_opportunities"] = 0
        self.assertIsNone(P.cell_rows(summary)[0]["detection_fraction"])

    def test_closed_synthetic_end_to_end_exports_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, audit, ready = write_closed_fixture(root)
            output = run / "presentation"
            result = P.present(workspace=root, run=run, audit=audit, readiness=ready, output=output, plots=False)
            self.assertEqual(result["native_or_provider_calls"], 0)
            self.assertEqual(result["tables"]["PRIMARY_MATCHED_CELLS.csv"], 224)
            findings = P.read_json(output / "FINDINGS.json")
            self.assertEqual(findings["independent_upstream_case_count"], 4)
            self.assertFalse(findings["tosem_readiness_established"])
            self.assertTrue(any("SAME two fault/repair states" in note for note in findings["scope_notes"]))
            with self.assertRaises(FileExistsError):
                P.present(workspace=root, run=run, audit=audit, readiness=ready, output=output, plots=False)

    def test_static_synthetic_plot_export_is_usable_when_matplotlib_exists(self):
        if importlib.util.find_spec("matplotlib") is None:
            self.skipTest("matplotlib is optional; do not install for this helper")
        summary, live, resource = fixture()
        tables = P.make_tables(summary, live, resource)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = P.plot_results(tables, out)
            self.assertEqual(len(result["files"]), 6)
            self.assertTrue(all((out / file).stat().st_size > 5000 for file in result["files"]))


if __name__ == "__main__":
    unittest.main()

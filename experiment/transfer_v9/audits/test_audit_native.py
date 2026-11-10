"""Synthetic fault tests; none execute a subject application or model."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from . import audit_native as A


def vector(**values):
    return {key: values.get(key, 0) for key in A.RESOURCES}


def ledger_fixture():
    manifest = {
        "prior_receipt_sha256": A.PRIOR_SHA, "prior_native_query_units": 4938,
        "prior_generation_allocation_seconds": 13459.630427200318,
        "old_campaign_envelope_unchanged": True,
        "phase_caps": vector(native_query_units=2, provider_chat_units=6,
                             generation_allocation_seconds=100, end_to_end_seconds=200),
        "cumulative_caps": {"native_query_units": 4940,
                            "generation_allocation_seconds": 13559.630427200318},
    }
    raw = A.canonical(manifest)
    events, previous = [], "0" * 64
    rows = [
        {"event": "reserve", "operation_id": "q1", "resources": vector(native_query_units=1), "role": "reference", "metadata": {}},
        {"event": "settle", "operation_id": "q1", "resources": vector(native_query_units=1), "status": "completed",
         "evidence": {}, "reservation_overrun_dimensions": []},
    ]
    for index, row in enumerate(rows, 1):
        row.update(index=index, previous_sha256=previous,
                   manifest_sha256=__import__("hashlib").sha256(raw).hexdigest())
        row["sha256"] = A.digest(row)
        previous = row["sha256"]
        events.append(row)
    return raw, events, {"event_count": len(events), "sha256": previous,
                         "manifest_sha256": __import__("hashlib").sha256(raw).hexdigest()}


def event_bytes(events):
    return b"".join(A.canonical(row) + b"\n" for row in events)


def reseal(events):
    previous = "0" * 64
    for row in events:
        row["previous_sha256"] = previous
        row["sha256"] = A.digest({key: value for key, value in row.items() if key != "sha256"})
        previous = row["sha256"]
    return {"event_count": len(events), "sha256": previous,
            "manifest_sha256": events[0]["manifest_sha256"]}


class IndependentAuditTests(unittest.TestCase):
    def test_sql_reference_is_recomputed_not_trusted(self):
        catalog = {"schema": "CREATE TABLE transfers(id INTEGER PRIMARY KEY,status TEXT,amount INTEGER);",
                   "rows": [[1, "WITHIN", 30], [2, "OUTSIDE", 70]]}
        task = {"family": "sql", "reference_sql": "SELECT SUM(amount) FROM transfers;", "expected_rows": [[100]]}
        result = A.independent_vanna(catalog, task, {"rows": [[100]], "figure": None, "error": None})
        self.assertTrue(result["reference_pass"])
        task["expected_rows"] = [[999]]
        with self.assertRaises(A.AuditError):
            A.independent_vanna(catalog, task, {"rows": [[999]], "figure": None, "error": None})

    def test_plot_contract_preserves_category_value_associations(self):
        catalog = {"schema": "CREATE TABLE transfers(id INTEGER PRIMARY KEY,status TEXT,amount INTEGER);",
                   "rows": [[1, "WITHIN", 30], [2, "OUTSIDE", 70]]}
        task = {"family": "figure", "reference_sql": "SELECT status,amount FROM transfers;",
                "expected_rows": [["WITHIN", 30], ["OUTSIDE", 70]]}
        output = {"rows": task["expected_rows"], "error": None,
                  "figure": {"data": [{"type": "bar", "x": ["WITHIN", "OUTSIDE"], "y": [30, 70]}]}}
        self.assertTrue(A.independent_vanna(catalog, task, output)["reference_pass"])
        output["figure"]["data"][0]["y"] = [70, 30]
        self.assertFalse(A.independent_vanna(catalog, task, output)["reference_pass"])

    def test_bool_is_not_a_numeric_database_value(self):
        self.assertFalse(A.rows_equal([[True]], [[1]]))
        self.assertTrue(A.rows_equal([["A", 1], ["A", 1]], [["A", 1], ["A", 1]]))
        self.assertFalse(A.rows_equal([["A", 1]], [["A", 1], ["A", 1]]))

    def test_form_missing_null_field_is_not_a_pass(self):
        task = {"kind": "form", "contract": {"slot_value": "London", "requested_slot": None, "active_loop": None}}
        self.assertFalse(A.independent_rasa(task, {"slot_value": "London", "requested_slot": None})["reference_pass"])
        self.assertTrue(A.independent_rasa(task, dict(task["contract"]))["reference_pass"])

    def test_original_ranking_failure_detected_without_prediction_accuracy_claim(self):
        task = {"kind": "ranking", "contract": {"ranking_length": 2, "valid_names": ["a", "b", "z"]}}
        output = {"intent": {"name": "z", "confidence": 0.8},
                  "intent_ranking": [{"name": "a", "confidence": 0.1}, {"name": "b", "confidence": 0.1}]}
        self.assertFalse(A.independent_rasa(task, output)["reference_pass"])
        output["intent_ranking"] = [output["intent"], {"name": "a", "confidence": 0.1}]
        self.assertTrue(A.independent_rasa(task, output)["reference_pass"])

    def test_ledger_independent_reconciliation(self):
        raw, events, head = ledger_fixture()
        result = A.verify_ledger(raw, event_bytes(events), head)
        self.assertEqual(result["totals"]["native_query_units"], 1)
        self.assertEqual(result["unsettled"], [])

    def test_torn_truncated_and_mutated_ledgers_rejected(self):
        raw, events, head = ledger_fixture()
        for data in (event_bytes(events)[:-1], event_bytes(events[:1]),
                     event_bytes(events).replace(b'"q1"', b'"q2"', 1)):
            with self.subTest(data=data), self.assertRaises(A.AuditError):
                A.verify_ledger(raw, data, head)

    def test_refunded_failed_native_attempt_rejected_even_with_valid_hash_chain(self):
        raw, events, head = ledger_fixture()
        events[-1]["resources"]["native_query_units"] = 0
        head = reseal(events)
        with self.assertRaises(A.AuditError):
            A.verify_ledger(raw, event_bytes(events), head)

    def test_unsettled_native_attempt_remains_charged(self):
        raw, events, _ = ledger_fixture()
        events = events[:1]
        head = reseal(events)
        result = A.verify_ledger(raw, event_bytes(events), head)
        self.assertEqual(result["unsettled"], ["q1"])
        self.assertEqual(result["totals"]["native_query_units"], 1)

    def test_over_cap_reservation_is_rejected_even_if_later_settlement_is_small(self):
        raw, events, _ = ledger_fixture()
        events[0]["resources"]["generation_allocation_seconds"] = 101
        head = reseal(events)
        with self.assertRaises(A.AuditError):
            A.verify_ledger(raw, event_bytes(events), head)

    def test_backend_generation_counter_excludes_queue_and_health_logs(self):
        text = "0 D que start_loop: processing new tasks\n" \
               "1 I slot launch_slot_: id 0 | task 3 | processing task, is_child = 0\n" \
               "2 I slot launch_slot_: id 0 | task 4 | processing task, is_child = 0\n" \
               "3 I srv log_server_r: GET /health 200\n"
        self.assertEqual(A.backend_generation_starts(text), 2)

    def test_no_host_absolute_or_parent_directory_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            for relative in ("C:/old-host/private.py", "/old-host/private.py", "../outside.py"):
                with self.subTest(relative=relative), self.assertRaises(A.AuditError):
                    A.safe(Path(directory), relative)

    def test_live_writer_blocks_before_reading_any_actual_case_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            (run / "accounting").mkdir(parents=True)
            (run / "accounting/WRITER_LOCK.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(A.AuditError, "actively written"):
                A.audit_stage(root, run, "development")

    def test_unclosed_stage_blocks_before_reading_case_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(A.AuditError, "has not closed"):
                A.audit_stage(root, root / "absent-run", "validation")

    def test_sdk_model_seed_cache_parent_and_costs_are_independently_bound(self):
        request = {"operation_id": "q1-chat1", "parent": "q1", "endpoint": "http://127.0.0.1:33009", "max_retries": 0,
                   "payload": {"model": "tosem-qwen2.5-7b-q4", "temperature": 0, "max_tokens": 256,
                               "messages": [{"role": "user", "content": "SQL please"}],
                               "extra_body": {"seed": 20261101, "cache_prompt": False}}}
        response = {"operation_id": "q1-chat1", "parent": "q1", "generation_allocation_seconds": 2.5,
                    "response": {"model": "tosem-qwen2.5-7b-q4", "choices": [{"message": {"content": "SELECT 1;"}}]}}
        settlement = {"status": "completed", "resources": vector(provider_chat_units=1, generation_allocation_seconds=2.5)}
        A.verify_provider(request, response, "q1-chat1", "q1", settlement)
        for change in ("parent", "cache", "model"):
            bad = deepcopy(request)
            if change == "parent":
                bad["parent"] = "foreign"
            elif change == "cache":
                bad["payload"]["extra_body"]["cache_prompt"] = True
            else:
                bad["payload"]["model"] = "other"
            with self.subTest(change=change), self.assertRaises(A.AuditError):
                A.verify_provider(bad, response, "q1-chat1", "q1", settlement)


class SyntheticLiveFixture(unittest.TestCase):
    """Four fabricated cells test provenance guards, never scientific effects."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        original = Path(__file__).resolve().parents[3]
        source = original / "experiment/transfer_v9"
        here = self.root / "experiment/transfer_v9"
        (here / "cohorts/validation").mkdir(parents=True)
        guide_path = self.root / "experiment/validation_v7/guidance/policy.py"
        guide_path.parent.mkdir(parents=True)
        shutil.copyfile(original / "experiment/validation_v7/guidance/policy.py", guide_path)
        shutil.copyfile(source / "cohorts/LIVE_CONFIRMATION_PLAN.json", here / "cohorts/LIVE_CONFIRMATION_PLAN.json")
        for setting in ("vanna", "rasa"):
            shutil.copyfile(source / f"cohorts/validation/{setting}.private.json", here / f"cohorts/validation/{setting}.private.json")
        self.run = self.root / "run"
        self.run.mkdir()
        (self.run / "STUDY_FREEZE.json").write_text("{}", encoding="utf-8")
        guide = A.frozen_guidance(self.root)
        cells = []
        for setting in ("vanna", "rasa"):
            tasks = [row["task_id"] for row in A.read(here / f"cohorts/validation/{setting}.private.json")["tasks"]]
            for method in ("CG1", "budgeted_retest_all"):
                directory = self.run / "validation/live-policy" / setting / method
                directory.mkdir(parents=True)
                profiles = []
                if method == "CG1":
                    for sample in range(3):
                        for i, task in enumerate(tasks):
                            frame = A.live_frame(setting, method, "live_profile", "H", task, sample)
                            profiles.append({"record_id": frame["operation_id"], "task_id": task, "state": "H",
                                "frame_role": "live_profile", "elapsed_seconds": 0.01 + i / 1000 + sample / 10000,
                                "checker_seconds": 0.00001, "feature_seconds": 0.00001,
                                "observed_dependency_tokens": A.CHANGES_A[setting] if i < 4 else [],
                                "receipt_sha256": A.digest(frame), "contract_pass": True})
                    public = {task: [{key: row[key] for key in ("elapsed_seconds", "observed_dependency_tokens", "receipt_sha256")}
                                     for row in profiles if row["task_id"] == task] for task in tasks}
                    costs = {task: 2 * __import__("statistics").median(row["elapsed_seconds"] for row in samples)
                             for task, samples in public.items()}
                    feature = A.digest({"trajectory": f"live-{setting}-{method}", "public_profiles": public})
                    impact = {"source": "paid_old_native_contexts", "feature_block_id": feature, "episode_index": 1,
                        "predecision": True, "current_or_future_outcomes_used": False, "provenance_verified": True,
                        "task_ids": tasks, "admitted_task_ids": tasks[:4], "changed_tokens": A.CHANGES_A[setting],
                        "evidence_receipt_sha256": A.digest(public)}
                    inputs = {"task_ids": tasks, "pair_cost_seconds": costs, "impact": impact, "history": [],
                        "trajectory_id": f"live-{setting}-{method}", "feature_block_id": feature, "episode_index": 1,
                        "changed_tokens": A.CHANGES_A[setting], "pair_limit": 2}
                    decision = guide.choose(**inputs)
                    selected = decision["nominal_prefix_task_ids"]
                else:
                    public, inputs = {}, None
                    selected = tasks
                    decision = {"nominal_prefix_task_ids": tasks}
                pre = {"method": method, "setting_id": setting, "case_id": A.CASES[setting][0],
                    "native_request_ceiling": 28, "guidance_sha256": A.GUIDANCE_SHA,
                    "actual_profile_operation_ids": [row["record_id"] for row in profiles],
                    "public_old_features": public, "guidance_inputs": inputs, "decision": decision,
                    "reference_or_current_new_outcomes_used": False, "history_initially_empty": True,
                    "controller_cpu_seconds": 0.001, "written_before_any_current_bad_state_call_in_this_cell": True}
                pre_path = directory / "PREDECISION.json"
                pre_path.write_bytes(A.canonical(pre))
                pairs = []
                for task in selected:
                    for state in ("H", "A"):
                        frame = A.live_frame(setting, method, "live_selected", state, task, predecision_sha=A.sha(pre_path))
                        pairs.append({"record_id": frame["operation_id"], "task_id": task, "state": state,
                            "frame_role": "live_selected", "elapsed_seconds": 0.02, "checker_seconds": 0.00001,
                            "feature_seconds": 0.00001, "receipt_sha256": A.digest(frame), "contract_pass": state == "H"})
                records = profiles + pairs
                cell = {"setting_id": setting, "method": method, "case_id": A.CASES[setting][0],
                    "native_request_ceiling": 28, "actual_profile_native_requests": len(profiles),
                    "actual_selected_native_requests": len(pairs), "actual_total_native_requests": len(records),
                    "unused_native_request_allowance": 28 - len(records), "selected_task_ids": selected,
                    "records": records, "predecision_path": pre_path.relative_to(self.root).as_posix(),
                    "predecision_sha256": A.sha(pre_path),
                    "allocated_native_and_checker_feature_wall_seconds": sum(row["elapsed_seconds"] + row["checker_seconds"] + row["feature_seconds"] for row in records),
                    "controller_cpu_seconds": 0.001}
                (directory / "RESULT.json").write_bytes(A.canonical(cell))
                cells.append(cell)
        self.bundle = {"schema": "v9-live-policy-confirmation-1", "cells": cells, "cells_planned": 4,
            "matched_native_request_ceiling_per_cell": 28,
            "registration_plan_sha256": A.sha(here / "cohorts/LIVE_CONFIRMATION_PLAN.json"),
            "study_freeze_sha256": A.sha(self.run / "STUDY_FREEZE.json")}
        self.save_bundle()

    def tearDown(self):
        self.temp.cleanup()

    def save_bundle(self):
        for cell in self.bundle["cells"]:
            directory = self.run / "validation/live-policy" / cell["setting_id"] / cell["method"]
            (directory / "RESULT.json").write_bytes(A.canonical(cell))
        (self.run / "LIVE_POLICY_CONFIRMATION.json").write_bytes(A.canonical(self.bundle))

    def test_four_live_cells_pay_88_actual_requests_under_matched_ceilings(self):
        frame, normalized, cells = A.live_plan_frames(self.root, self.run)
        self.assertEqual(len(frame), 88)
        self.assertEqual(len(normalized), 88)
        self.assertEqual(len(cells), 4)
        self.assertEqual([cell["cell"]["actual_total_native_requests"] for cell in cells], [28, 16, 28, 16])

    def test_profile_truth_fields_cannot_change_live_predecision(self):
        for cell in self.bundle["cells"]:
            for row in cell["records"]:
                row["contract_pass"] = not row["contract_pass"]
        self.save_bundle()
        frame, _, _ = A.live_plan_frames(self.root, self.run)
        self.assertEqual(len(frame), 88)

    def test_profile_verdict_injection_into_public_features_is_rejected(self):
        cell = self.bundle["cells"][0]
        pre_path = A.safe(self.root, cell["predecision_path"])
        pre = A.read(pre_path)
        next(iter(pre["public_old_features"].values()))[0]["contract_pass"] = True
        pre_path.write_bytes(A.canonical(pre))
        cell["predecision_sha256"] = A.sha(pre_path)
        self.save_bundle()
        with self.assertRaises(A.AuditError):
            A.live_plan_frames(self.root, self.run)

    def test_profile_cannot_replace_a_fresh_selected_endpoint(self):
        cell = self.bundle["cells"][0]
        cell["records"][24]["record_id"] = cell["records"][0]["record_id"]
        self.save_bundle()
        with self.assertRaises(A.AuditError):
            A.live_plan_frames(self.root, self.run)


if __name__ == "__main__":
    unittest.main()

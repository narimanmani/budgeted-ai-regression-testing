"""Independent read-only audit of CLOSED v9 acquisition stages.

Uses only the standard library. It imports no application, collector, checker,
provider, ledger writer or replay implementation and makes no network calls.
Raw historical Vanna method paths are resolved solely through the registered
case/version inventory; their original host-absolute paths are never followed.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics

COUNTS = ("native_query_units", "queryfree_native_check_units", "provider_chat_units", "provider_embedding_units")
TIMES = ("generation_allocation_seconds", "end_to_end_seconds")
RESOURCES = COUNTS + TIMES
PRIOR_SHA = "c6f1612ee8ce6a72c10020007d0e73d50a4da0ff5dae9d68ca4851520f3b2004"
GUIDANCE_SHA = "f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989"
RASA_CLOSURE = "a05b457afdb74e86aa1fe8426866817915c5f43d0a0be03db593c20ca2c86f30"
RASA_PIN = "f3b733a0c1f1ba9a9b20cac806648dbff2c5d467"
IMAGE = "rasa/rasa@sha256:a48a3523e70997282c4ab8fd86bd4702f29178a840bcfd6b673b21704f731652"
CASES = {"vanna": ("VANNA_SQL_WITHIN", "VANNA_ASK_FIGURE"),
         "rasa": ("RASA_FORM_TRIGGER", "RASA_INTENT_RANKING")}
CHANGES_A = {"vanna": ["code:src/vanna/base/base.py/extract_sql"],
             "rasa": ["code:rasa/core/actions/forms.py", "code:rasa/core/actions/loops.py"]}


class AuditError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def safe(root, relative):
    relative = str(relative).replace("\\", "/")
    require(not Path(relative).is_absolute() and not re.match(r"^[A-Za-z]:", relative), "Host-absolute fallback is forbidden")
    root = Path(root).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AuditError("Artifact path escapes its declared workspace") from exc
    return path


def measured(value, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def resource_vector(value):
    require(isinstance(value, dict) and set(value) == set(RESOURCES), "Incomplete resource vector")
    require(all(type(value[k]) is int and value[k] >= 0 for k in COUNTS), "Invalid resource count")
    require(all(measured(value[k]) for k in TIMES), "Invalid resource duration")
    return value


def rows_equal(actual, expected):
    def valid(rows):
        return isinstance(rows, list) and all(isinstance(row, (list, tuple)) and all(
            item is None or isinstance(item, str) or (type(item) in (int, float) and math.isfinite(item))
            for item in row) for row in rows)
    return bool(valid(actual) and valid(expected) and Counter(tuple(row) for row in actual) == Counter(tuple(row) for row in expected))


def reference_sql(catalog, task):
    """Recompute finite expected values in a separate in-memory SQLite database."""
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute(catalog["schema"])
        connection.executemany("INSERT INTO transfers VALUES (?, ?, ?)", catalog["rows"])
        connection.execute("PRAGMA query_only = ON")
        expected = [list(row) for row in connection.execute(task["reference_sql"]).fetchall()]
    require(rows_equal(expected, task["expected_rows"]), "Frozen expected SQL rows disagree with independently executed reference SQL")
    return expected


def independent_vanna(catalog, task, output):
    expected = reference_sql(catalog, task)
    semantic = rows_equal(output.get("rows"), expected)
    figure = output.get("figure")
    exists = isinstance(figure, dict) and bool(figure.get("data"))
    grounded = False
    if exists:
        pairs, valid = [], True
        categorical = any(isinstance(row[0], str) for row in expected)
        for trace in figure["data"]:
            if not isinstance(trace, dict):
                valid = False
                continue
            xs, ys = trace.get("x", []), trace.get("y", [])
            if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys):
                valid = False
                continue
            valid = valid and trace.get("type") in (("bar",) if categorical else ("scatter", "scattergl"))
            current = list(zip(xs, ys))
            if categorical and trace.get("orientation") == "h":
                current = [(label, number) for number, label in current]
            pairs.extend([list(pair) for pair in current])
        grounded = bool(valid and rows_equal(pairs, expected))
    passed = semantic and output.get("error") is None
    if task["family"] == "figure":
        passed = passed and exists and grounded
    elif task["family"] == "ask_no_figure":
        passed = passed and figure is None
    return {"reference_pass": bool(passed), "result_rows_correct": bool(semantic),
            "returned_figure_nonempty": bool(exists), "figure_values_grounded": bool(grounded)}


def independent_rasa(task, output):
    contract = task["contract"]
    if task["kind"] == "form":
        clauses = {key: key in output and output[key] == contract[key]
                   for key in ("slot_value", "requested_slot", "active_loop")}
    else:
        ranking = output.get("intent_ranking", [])
        require(isinstance(ranking, list) and all(isinstance(item, dict) for item in ranking), "Malformed native ranking")
        confidence = [item.get("confidence") for item in ranking]
        valid_confidence = all(measured(number) and number <= 1 for number in confidence)
        clauses = {
            "ranking_length": len(ranking) == contract["ranking_length"],
            "first_equals_intent": bool(ranking) and ranking[0] == output.get("intent"),
            "sorted_confidences": valid_confidence and all(confidence[i] >= confidence[i + 1] for i in range(len(confidence) - 1)),
            "valid_names": all(item.get("name") in contract["valid_names"] for item in ranking),
            "confidence_interval": valid_confidence,
        }
    return {"reference_pass": all(clauses.values()), "clauses": clauses}


def verify_ledger(manifest_bytes, events_bytes, head):
    """Pure independent ledger verifier; never acquires a writer lock."""
    manifest, manifest_sha = json.loads(manifest_bytes), hashlib.sha256(manifest_bytes).hexdigest()
    caps = resource_vector(manifest["phase_caps"])
    require(manifest["prior_receipt_sha256"] == PRIOR_SHA and manifest["prior_native_query_units"] == 4938,
            "Historical query baseline changed")
    require(manifest["prior_generation_allocation_seconds"] == 13459.630427200318,
            "Historical generation allocation changed")
    require(manifest["cumulative_caps"] == {
        "native_query_units": 4938 + caps["native_query_units"],
        "generation_allocation_seconds": 13459.630427200318 + caps["generation_allocation_seconds"]}, "Cumulative caps omit prior work")
    require(manifest["old_campaign_envelope_unchanged"] is True, "Closed prior account reopened")
    require(not events_bytes or events_bytes.endswith(b"\n"), "Torn event ledger")
    previous, events, reserves, settles = "0" * 64, [], {}, {}
    running = {key: 0 for key in RESOURCES}
    dispatch_blocked = False
    for line in events_bytes.splitlines():
        row = json.loads(line)
        body = {key: value for key, value in row.items() if key != "sha256"}
        require(row.get("sha256") == digest(body) and row.get("previous_sha256") == previous,
                "Ledger chain/hash changed")
        require(row.get("manifest_sha256") == manifest_sha and row.get("index") == len(events) + 1,
                "Cross-phase or reordered event")
        ident = row.get("operation_id")
        require(isinstance(ident, str) and ident, "Operation identity missing")
        vector = resource_vector(row["resources"])
        if row["event"] == "reserve":
            require(ident not in reserves, "Duplicate native/provider/setup operation identity")
            require(not dispatch_blocked and all(running[key] + vector[key] <= caps[key] for key in RESOURCES),
                    "Reservation exceeded its prospective cap or followed an overrun")
            reserves[ident] = row
            for key in RESOURCES:
                running[key] += vector[key]
        elif row["event"] == "settle":
            require(ident in reserves and ident not in settles, "Missing or duplicate settlement")
            require(row["status"] in ("completed", "failed", "timed_out"), "Unknown settlement status")
            require(all(vector[k] == reserves[ident]["resources"][k]
                        for k in ("native_query_units", "queryfree_native_check_units")), "Native attempt refunded")
            overrun = [key for key in RESOURCES if vector[key] > reserves[ident]["resources"][key]]
            require(row.get("reservation_overrun_dimensions") == overrun, "Incorrect operation-overrun flag")
            for key in RESOURCES:
                running[key] += vector[key] - reserves[ident]["resources"][key]
            dispatch_blocked = dispatch_blocked or bool(overrun) or any(running[key] > caps[key] for key in RESOURCES)
            settles[ident] = row
        else:
            raise AuditError("Unknown resource event")
        previous = row["sha256"]
        events.append(row)
    require(head == {"event_count": len(events), "sha256": previous, "manifest_sha256": manifest_sha}, "Ledger checkpoint mismatch")
    totals = {key: 0 for key in RESOURCES}
    for ident, reservation in reserves.items():
        row = settles.get(ident, reservation)
        for key in RESOURCES:
            totals[key] += row["resources"][key]
    return {"events": events, "reserves": reserves, "settles": settles, "totals": totals,
            "unsettled": sorted(set(reserves) - set(settles)),
            "over_cap": [key for key in RESOURCES if totals[key] > caps[key]],
            "operation_overruns": {ident: row["reservation_overrun_dimensions"]
                for ident, row in settles.items() if row["reservation_overrun_dimensions"]}}


def source_bindings(workspace, inventory):
    result = {}
    for case in inventory["case_candidates"]:
        for binding in case["bindings"]:
            path = safe(workspace, binding["local_path"])
            data = path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            require(len(data) == binding["bytes"] and sha(path) == binding["sha256"] and blob == binding["git_blob_sha1"],
                    "Upstream source file/Git-blob binding changed")
            key = (case["case_id"], binding["state"], binding["path"])
            require(key not in result, "Duplicate upstream source binding")
            result[key] = (binding, path)
    return result


def expected_state_digest(here, setting, state, cohort, inventory, dependency_receipt_sha256=None):
    production = []
    by_id = {case["case_id"]: case for case in inventory["case_candidates"]}
    for index, case_id in enumerate(CASES[setting]):
        version = "parent" if state == ("A" if index == 0 else "B") else "fixed"
        for binding in by_id[case_id]["bindings"]:
            if binding["state"] == version and binding["path"].endswith(".py") and not binding["path"].startswith("tests/"):
                production.append((binding["path"], binding["sha256"]))
    public = here / f"cohorts/{cohort}/" / ("rasa.public.json" if setting == "rasa" else "vanna.datasource.json")
    original = digest({"setting": setting, "production_bindings": production,
        "public_catalog_sha256": sha(public), "runtime_adapter_sha256": sha(here / f"runtime/{setting}_native.py"),
        "model_runtime": IMAGE if setting == "rasa" else "Qwen2.5-7B-Q4/4096ctx/256out/temp0/cacheoff"})
    if setting == "rasa" and dependency_receipt_sha256 is not None:
        return digest({"frozen_core_state_digest": original,
                       "locked_missing_dependency_receipt_sha256": dependency_receipt_sha256})
    return original


def verify_vanna_methods(output, state, bindings):
    expected = {"VANNA_SQL_WITHIN": "extract_sql", "VANNA_ASK_FIGURE": "ask"}
    rows = output.get("method_bindings", [])
    require(len(rows) == 2 and {row["case_id"] for row in rows} == set(expected), "Missing/duplicate Vanna historical method")
    for row in rows:
        cid = row["case_id"]
        version = "parent" if state == ("A" if cid == "VANNA_SQL_WITHIN" else "B") else "fixed"
        require(row["historical_version"] == version and row["method"] == expected[cid], "Wrong historical method state")
        # Resolve only through registered case/version. Never follow row['path'].
        binding, path = bindings[(cid, version, "src/vanna/base/base.py")]
        require(row["sha256"] == binding["sha256"], "Method file differs from independently sourced authority")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "VannaBase")
        method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == expected[cid])
        dump = ast.dump(method, include_attributes=False)
        candidates = {digest(dump), digest(dump.replace(", type_params=[]", ""))}
        require(row["method_ast_sha256"] in candidates, "Historical method AST commitment changed or Python AST version unsupported")
    require(output.get("actual_local_generation") is True and output.get("sqlite_execution") is True,
            "Native SQL/provider scope receipt absent")
    expected_tokens = sorted("code:src/vanna/base/base.py/" + name for name in output.get("production_calls", [])
                             if name in ("extract_sql", "ask", "get_plotly_figure", "generate_sql"))
    require(output.get("trace_tokens") == expected_tokens, "Function evidence is not the recorded native call projection")


def verify_provider(request, response, ident, parent, settle):
    require(request["operation_id"] == ident and response["operation_id"] == ident
            and request["parent"] == parent and response["parent"] == parent, "SDK parent/call identity mismatch")
    require(request["endpoint"] == "http://127.0.0.1:33009" and request["max_retries"] == 0, "SDK endpoint/retry policy changed")
    payload = request["payload"]
    require(payload.get("model") == "tosem-qwen2.5-7b-q4" and payload.get("temperature") == 0
            and payload.get("max_tokens") == 256, "Pinned SDK model/generation settings changed")
    require(payload.get("extra_body") == {"seed": 20261101, "cache_prompt": False}, "Cache/seed policy changed")
    require(isinstance(payload.get("messages"), list) and bool(payload["messages"]), "No actual model messages recorded")
    result = response["response"]
    require(result.get("model") == "tosem-qwen2.5-7b-q4" and isinstance(result.get("choices"), list)
            and len(result["choices"]) == 1, "Missing actual SDK model response")
    require(isinstance(result["choices"][0].get("message", {}).get("content"), str), "SDK response content missing")
    require(settle["status"] == "completed" and settle["resources"]["provider_chat_units"] == 1
            and settle["resources"]["generation_allocation_seconds"] == response["generation_allocation_seconds"], "SDK cost/settlement mismatch")


def backend_generation_starts(text):
    return sum(bool(re.search(r"\bslot\s+\S+.*\bprocessing task,\s*is_child\s*=\s*0\b", line))
               for line in text.splitlines())


def frozen_guidance(workspace):
    path = Path(workspace) / "experiment/validation_v7/guidance/policy.py"
    require(sha(path) == GUIDANCE_SHA, "Original pure CG1 code changed")
    spec = importlib.util.spec_from_file_location("independent_audit_original_cg1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def live_frame(setting, method, role, state, task, sample=0, predecision_sha=None):
    prefix = "cg1" if method == "CG1" else method
    ident = (f"live-{setting}-{prefix}-profile-p{sample}-{task}" if role == "live_profile" else
             f"live-{setting}-{prefix}-pair-{task}-" + ("old" if state == "H" else "new"))
    row = {"operation_id": ident, "task_id": task, "state": state,
           "case_id": CASES[setting][0], "pass_index": sample, "frame_role": role}
    if predecision_sha is not None:
        row["predecision_sha256"] = predecision_sha
    return row


def live_plan_frames(workspace, run):
    """Reconstruct every prospective live cell from its public predecision inputs."""
    here = Path(workspace) / "experiment/transfer_v9"
    bundle = read(Path(run) / "LIVE_POLICY_CONFIRMATION.json")
    require(bundle["schema"] == "v9-live-policy-confirmation-1" and bundle["cells_planned"] == 4,
            "Live confirmation is not the four-cell registered addition")
    require(bundle["matched_native_request_ceiling_per_cell"] == 28
            and bundle["registration_plan_sha256"] == sha(here / "cohorts/LIVE_CONFIRMATION_PLAN.json")
            and bundle["study_freeze_sha256"] == sha(Path(run) / "STUDY_FREEZE.json"), "Live confirmation registration changed")
    expected_cells = [(setting, method) for setting in ("vanna", "rasa") for method in ("CG1", "budgeted_retest_all")]
    require([(cell["setting_id"], cell["method"]) for cell in bundle["cells"]] == expected_cells,
            "Live cells replaced, omitted or reordered after outcomes")
    guide = frozen_guidance(workspace)
    planned, normalized, descriptors = {}, [], []
    for cell in bundle["cells"]:
        setting, method = cell["setting_id"], cell["method"]
        directory = Path(run) / "validation/live-policy" / setting / method
        require(read(directory / "RESULT.json") == cell, "Top-level live results differ from their original per-cell receipts")
        pre_path = safe(workspace, cell["predecision_path"])
        require(pre_path == (directory / "PREDECISION.json").resolve()
                and sha(pre_path) == cell["predecision_sha256"], "Live predecision path/hash changed")
        pre = read(pre_path)
        require(pre["setting_id"] == setting and pre["method"] == method and pre["case_id"] == CASES[setting][0]
                and pre["guidance_sha256"] == GUIDANCE_SHA and pre["native_request_ceiling"] == 28,
                "Live public predecision identity changed")
        require(pre["reference_or_current_new_outcomes_used"] is False and pre["history_initially_empty"] is True
                and pre["written_before_any_current_bad_state_call_in_this_cell"] is True, "Live reference/history boundary declaration missing")
        catalog = read(here / f"cohorts/validation/{setting}.private.json")
        tasks = [task["task_id"] for task in catalog["tasks"]]
        records = cell["records"]
        require(len({row["record_id"] for row in records}) == len(records), "Live output identities were reused")
        profiles = [row for row in records if row["frame_role"] == "live_profile"]
        pairs = [row for row in records if row["frame_role"] == "live_selected"]
        if method == "CG1":
            profile_frames = [live_frame(setting, method, "live_profile", "H", task, sample)
                              for sample in range(3) for task in tasks]
            require([row["record_id"] for row in profiles] == [row["operation_id"] for row in profile_frames],
                    "Live CG1 does not pay the complete fresh 24-query profile in registered order")
            public = {}
            for task in tasks:
                samples = [row for row in profiles if row["task_id"] == task]
                require(len(samples) == 3 and all(row["state"] == "H" for row in samples), "Live profiles must contain exactly three OLD observations per task")
                public[task] = [{key: row[key] for key in ("elapsed_seconds", "observed_dependency_tokens", "receipt_sha256")}
                                for row in samples]
            costs = {task: 2 * statistics.median(sample["elapsed_seconds"] for sample in samples)
                     for task, samples in public.items()}
            changed = CHANGES_A[setting]
            admitted = [task for task in tasks if any(set(sample["observed_dependency_tokens"]).intersection(changed)
                                                     for sample in public[task])]
            feature = digest({"trajectory": f"live-{setting}-{method}", "public_profiles": public})
            impact = {"source": "paid_old_native_contexts", "feature_block_id": feature,
                "episode_index": 1, "predecision": True, "current_or_future_outcomes_used": False,
                "provenance_verified": True, "task_ids": tasks, "admitted_task_ids": admitted,
                "changed_tokens": changed, "evidence_receipt_sha256": digest(public)}
            inputs = {"task_ids": tasks, "pair_cost_seconds": costs, "impact": impact,
                "history": [], "trajectory_id": f"live-{setting}-{method}", "feature_block_id": feature,
                "episode_index": 1, "changed_tokens": changed, "pair_limit": 2}
            require(pre["public_old_features"] == public and pre["guidance_inputs"] == inputs,
                    "Live guidance consumed more than whitelisted actual OLD costs/paths, or changed profile estimator")
            require(pre["decision"] == guide.choose(**inputs), "Live choice differs from original frozen CG1")
            selected = pre["decision"]["nominal_prefix_task_ids"]
        else:
            profile_frames, public = [], {}
            require(not profiles and pre["public_old_features"] == {} and pre["guidance_inputs"] is None,
                    "Simple full retesting bought or borrowed hidden profile evidence")
            selected = tasks
            require(pre["decision"]["nominal_prefix_task_ids"] == tasks, "Retest-all changed its registered complete catalog order")
        require(pre["actual_profile_operation_ids"] == [row["record_id"] for row in profiles], "Live profile receipt list changed")
        selected_frames = [live_frame(setting, method, "live_selected", state, task,
                                      predecision_sha=cell["predecision_sha256"])
                           for task in selected for state in ("H", "A")]
        require([row["record_id"] for row in pairs] == [row["operation_id"] for row in selected_frames], "Fresh live endpoint order differs from sealed selection")
        require(cell["selected_task_ids"] == selected and cell["case_id"] == CASES[setting][0], "Live case or selected tasks changed")
        count = len(profiles) + len(pairs)
        require(count <= 28 and cell["native_request_ceiling"] == 28
                and cell["actual_profile_native_requests"] == len(profiles)
                and cell["actual_selected_native_requests"] == len(pairs)
                and cell["actual_total_native_requests"] == count
                and cell["unused_native_request_allowance"] == 28 - count, "Live complete request accounting does not reconcile")
        allocated = sum(row["elapsed_seconds"] + row["checker_seconds"] + row["feature_seconds"] for row in records)
        require(math.isclose(cell["allocated_native_and_checker_feature_wall_seconds"], allocated, rel_tol=1e-12)
                and measured(pre["controller_cpu_seconds"]) and cell["controller_cpu_seconds"] == pre["controller_cpu_seconds"],
                "Live allocation/controller CPU accounting changed")
        for row in profile_frames + selected_frames:
            require(row["operation_id"] not in planned, "Live operation identity is duplicated between cells")
            planned[row["operation_id"]] = (setting, row)
        normalized += records
        descriptors.append({"cell": cell, "predecision": pre,
            "profile_ids": [row["record_id"] for row in profiles],
            "selected_ids": [row["record_id"] for row in pairs]})
    require(len(planned) <= 88 and len(normalized) == len(planned), "Live addition exceeds its prospective native-request envelope")
    return planned, normalized, descriptors


def audit_live_outcomes(descriptors, observations, reserves, settles):
    result = []
    for descriptor in descriptors:
        cell = descriptor["cell"]
        profile_indices = [settles[ident]["index"] for ident in descriptor["profile_ids"]]
        selected_indices = [reserves[ident]["index"] for ident in descriptor["selected_ids"]]
        if profile_indices and selected_indices:
            require(max(profile_indices) < min(selected_indices), "Live current endpoints dispatched before OLD profile acquisition closed")
        outcomes = []
        for task in cell["selected_task_ids"]:
            rows = [observations[ident] for ident in descriptor["selected_ids"]
                    if observations[ident]["frame"]["task_id"] == task]
            require(len(rows) == 2 and [row["frame"]["state"] for row in rows] == ["H", "A"], "Live selected pair lost an endpoint")
            old, new = rows
            old_pass, new_pass = old["verdict"]["reference_pass"], new["verdict"]["reference_pass"]
            outcomes.append({"task_id": task, "old_record_id": old["frame"]["operation_id"],
                "new_record_id": new["frame"]["operation_id"], "old_contract_pass": old_pass,
                "new_contract_pass": new_pass, "observed_contract_regression": old_pass and not new_pass,
                "old_receipt_sha256": sha(old["path"]), "new_receipt_sha256": sha(new["path"])})
        require(cell["outcomes"] == outcomes and cell["observed_contract_regression_pairs"]
                == sum(row["observed_contract_regression"] for row in outcomes), "Live detected transitions differ from independently checked fresh endpoints")
        for ident in descriptor["selected_ids"]:
            require(reserves[ident]["metadata"].get("predecision_sha256") == cell["predecision_sha256"],
                    "Fresh live endpoint reservation did not bind its predecision BEFORE dispatch")
        result.append({"setting_id": cell["setting_id"], "method": cell["method"],
            "native_request_ceiling": 28, "actual_native_requests": cell["actual_total_native_requests"],
            "observed_fresh_contract_regressions": cell["observed_contract_regression_pairs"],
            "predecision_bound_before_dispatch": True, "independent_cases_added": 0})
    return result


def engineering_context(workspace, run, stage, ledger, completed, stopped):
    """Resolve only an explicit prospectively sealed retry; never search hosts."""
    base = Path(run)
    here = Path(workspace) / "experiment/transfer_v9"
    frame = read(here / "cohorts/FRAME.json")[stage]
    result = {"data_root": base, "frame": frame, "stopped": stopped,
              "model_startup_id": stage + "-model-startup", "amendment": None,
              "retained_original_incidents": []}
    amendment_path = base / "ENGINEERING_AMENDMENT.json"
    if not amendment_path.exists():
        return result
    amendment = read(amendment_path)
    freeze = read(base / "ENGINEERING_AMENDMENT_FREEZE.json")
    require(amendment.get("schema") == "v9-prospective-engineering-amendment-1"
            and amendment["prior_study_freeze_sha256"] == sha(base / "STUDY_FREEZE.json"), "Engineering amendment belongs to a different study")
    for relative, binding in freeze["files"].items():
        path = safe(workspace, relative)
        require(path.stat().st_size == binding["bytes"] and sha(path) == binding["sha256"], "Engineering amendment source/dependency declaration changed")
    require(amendment["output_subdirectory"] == "engineering_retry2" and amendment["operation_id_prefix"] == "retry2-",
            "Undeclared engineering retry namespace")
    require(all(amendment[key] is False for key in ("counter_reset", "numerical_cap_increase",
        "original_core_source_or_data_bytes_changed", "prompt_checker_guidance_model_or_generation_settings_changed",
        "qualification_criteria_changed", "new_first_launch_success_claimed")), "Engineering retry changed scientific conditions or accounting")
    require(amendment["original_model_provider_boundaries"] == 0 and amendment["native_or_model_answers_seen"] == 0
            and amendment["retained_failed_native_attempts"] == 1
            and amendment["complete_new_phase_attempt_ceiling_after_retained_failure"] == 377
            and amendment["native_case_operation_cap_unchanged"] == 400, "Retry scope exceeds the sealed engineering-only addition")
    require(amendment["original_stop_sha256"] == sha(base / "DEVELOPMENT_STOP.json")
            and amendment["retry_frame_sha256"] == sha(base / "ENGINEERING_RETRY_FRAME.json")
            and amendment["environment_addition_sha256"] == sha(base / "ENGINEERING_ENVIRONMENT_ADDITION.json")
            and amendment["new_orchestrator_sha256"] == sha(here / "amendments/dependency_retry.py"), "Engineering amendment commitments changed")
    environment = read(base / "ENGINEERING_ENVIRONMENT_ADDITION.json")
    require(environment["packages"]["requests"] == "2.32.3"
            and environment["packages"]["urllib3"] == "2.8.0"
            and environment["application_instances_or_model_calls_in_preflight"] == 0,
            "Engineering amendment is not the declared missing dependency repair")
    previous_environment = read(base / "PYTHON_ENVIRONMENT.json")["packages"]
    require(all(environment["packages"][key] == value for key, value in previous_environment.items()
                if key in environment["packages"]), "Previously recorded core package versions changed")
    retry_frame = read(base / "ENGINEERING_RETRY_FRAME.json")
    development_frame = read(here / "cohorts/FRAME.json")["development"]
    expected = {sid: [{**row, "operation_id": "retry2-" + row["operation_id"]} for row in development_frame[sid]]
                for sid in ("vanna", "rasa")}
    require(retry_frame == expected, "Retry replaced cases, tasks, conditions or scientific admission requirements")
    require(not list((base / "development/provider").glob("*-request.json")), "Original dependency failure had a model boundary")
    require(backend_generation_starts((base / "development/backend/backend.log").read_text(encoding="utf-8", errors="replace")) == 0,
            "Original backend generated an answer before the dependency repair")
    original_raws = sorted((base / "development/raw").glob("*.json"))
    require(len(original_raws) == 1, "Original failed attempts were omitted or expanded")
    for path in original_raws:
        raw = read(path)
        ident = raw["operation_id"]
        require(raw.get("status") == "study_incident" and raw.get("exception_type") == "ModuleNotFoundError"
                and "requests" in raw.get("message", ""), "Original engineering failure was reclassified as a product result")
        require(ident in ledger["reserves"] and ident in ledger["settles"]
                and ledger["reserves"][ident]["resources"]["native_query_units"] == 1
                and ledger["settles"][ident]["status"] == "failed"
                and ledger["settles"][ident]["evidence"]["incident_sha256"] == sha(path), "Original failed native attempt was not retained and paid")
        result["retained_original_incidents"].append({"operation_id": ident, "raw_sha256": sha(path),
            "native_attempts_retained": 1, "model_boundaries": 0})
    original_closed = read(base / "development/backend/CLOSED.json")
    original_owner = read(base / "development/backend/OWNER.json")
    original_ready = read(base / "development/backend/READY.json")
    require(original_closed["pid"] == original_owner["pid"] and original_closed["returncode"] is not None
            and original_closed["only_owned_popen_handle_closed"] is True, "Original owned backend was not closed")
    original_startup = ledger["settles"].get("development-model-startup", {})
    require(original_startup.get("status") == "completed"
            and original_startup["resources"]["generation_allocation_seconds"]
            == original_ready["startup_generation_allocation_seconds"], "Original startup allocation was reset or omitted")
    if completed or stage == "validation":
        gate = read(base / "DEVELOPMENT_GATE.json")
        require(gate["engineering_amendment_sha256"] == sha(amendment_path)
                and gate["original_first_launch_failed"] is True and gate["failed_attempt_retained"] is True
                and gate["original_first_launch_reported_successful"] is False, "Completed retry lost its original failure attribution")
        if not (base / "RASA_DEPENDENCY_AMENDMENT.json").exists():
            require(gate["completed_output_subdirectory"] == "engineering_retry2", "Unexpected development output override")
    child = safe(base, amendment["output_subdirectory"])
    if stage == "development":
        require(completed or (child / "DEVELOPMENT_RETRY_STOP.json").exists(), "Engineering retry has not closed")
    amendment_time = datetime.fromisoformat(freeze["at_utc"])
    retry_reservations = [row for ident, row in ledger["reserves"].items()
                          if ident.startswith("retry2-") or ident == "dependency-retry2-model-startup"
                          or ident.startswith("development-rasa-startup-")]
    require(all(datetime.fromisoformat(row["at_utc"]) >= amendment_time for row in retry_reservations),
            "Engineering retry dispatched before its source/dependency amendment was frozen")
    if stage == "development":
        result.update(data_root=child, frame=retry_frame, stopped=not completed,
                      model_startup_id="dependency-retry2-model-startup")
    result.update(amendment={
                      "sha256": sha(amendment_path), "freeze_sha256": sha(base / "ENGINEERING_AMENDMENT_FREEZE.json"),
                      "original_stopped_frame_remains_stopped": True,
                      "retry_changes_only_dependency_environment_and_operation_namespace": True})
    return result


def rasa_dependency_context(workspace, run, stage, ledger, completed, context):
    """Verify the separate, locked missing-channel dependency and mixed roots."""
    base, here = Path(run), Path(workspace) / "experiment/transfer_v9"
    amendment_path = base / "RASA_DEPENDENCY_AMENDMENT.json"
    if not amendment_path.exists():
        return context
    amendment = read(amendment_path)
    freeze_path = base / "RASA_DEPENDENCY_AMENDMENT_FREEZE.json"
    freeze = read(freeze_path)
    for relative, binding in freeze["files"].items():
        path = safe(workspace, relative)
        require(path.stat().st_size == binding["bytes"] and sha(path) == binding["sha256"], "Locked Rasa dependency amendment changed")
    require(amendment["schema"] == "v9-prospective-rasa-dependency-amendment-1"
            and amendment["original_study_freeze_sha256"] == sha(base / "STUDY_FREEZE.json")
            and amendment["first_amendment_freeze_sha256"] == sha(base / "ENGINEERING_AMENDMENT_FREEZE.json"),
            "Rasa dependency addition belongs to a different study")
    require(all(amendment[key] is False for key in ("original_core_source_bytes_edited", "questions_contracts_prompt_or_guide_changed",
        "docker_base_image_changed", "counter_reset", "new_policy_or_case_selection_based_on_outcomes")), "Rasa engineering repair changed scientific conditions")
    require(amendment["rasa_model_answers_or_task_queries_seen_before_amendment"] == 0
            and amendment["completed_vanna_observations_reused_without_rerun"] == 16
            and amendment["same_original_phase_ledger_and_caps"] is True
            and amendment["complete_native_case_attempt_plan_including_failure"] == 377
            and amendment["cap_unchanged"] == 400, "Rasa repair changed observation or resource scope")
    env = here / "amendments/rasa_env"
    receipt_path = env / "DEPENDENCY_RECEIPT.json"
    receipt, manifest = read(receipt_path), read(env / "INSTALLED_MANIFEST.json")
    require(amendment["dependency_receipt_sha256"] == sha(receipt_path)
            and receipt["installed_manifest_sha256"] == sha(env / "INSTALLED_MANIFEST.json")
            and receipt["import_probe_sha256"] == sha(env / "IMPORT_PROBE.json"), "Mounted dependency/probe commitments changed")
    actual_files = {path.relative_to(env / "pydeps").as_posix(): {"sha256": sha(path), "bytes": path.stat().st_size}
                    for path in sorted((env / "pydeps").rglob("*")) if path.is_file()}
    require(manifest["files"] == actual_files and receipt["dependency_commitment_sha256"] == digest(actual_files),
            "Mounted pure-Python dependency bytes changed")
    require(receipt["version"] == "4.7.0" and receipt["original_image"] == IMAGE and receipt["image_changed"] is False
            and receipt["native_task_queries"] == receipt["model_training_calls"] == receipt["provider_boundaries"] == 0,
            "Dependency installation was mislabeled native/model task work")
    source = read(env / "PACKAGE_SOURCE.json")
    metadata = read(env / "PYPI_METADATA.json")
    matching = [row for row in metadata["urls"] if row["filename"] == source["filename"]]
    artifact = safe(env / "downloads", source["filename"])
    require(len(matching) == 1 and source["version"] == metadata["info"]["version"] == "4.7.0"
            and source["sha256"] == matching[0]["digests"]["sha256"] == sha(artifact)
            and source["bytes"] == matching[0]["size"] == artifact.stat().st_size,
            "Official PyPI dependency version/artifact SHA does not match installed-source commitment")
    lock_path = safe(workspace, amendment["original_source_poetry_lock"])
    lock_text = lock_path.read_text(encoding="utf-8")
    require(receipt["source_lock_sha256"] == sha(lock_path)
            and re.search(r'name\s*=\s*"pytelegrambotapi"\s*\nversion\s*=\s*"4\.7\.0"', lock_text)
            and re.search(r'^pytelegrambotapi\s*=\s*\[\s*\]', lock_text, re.M)
            and source["artifact_hash_not_present_in_source_lock"] is True,
            "Source lock pins the version but does not contain the claimed artifact hash")
    probe = read(env / "IMPORT_PROBE.json")
    require(probe["passed"] is True and probe["pyTelegramBotAPI_version"] == "4.7.0"
            and len(probe["origins"]) == 18
            and probe["native_tasks"] == probe["model_training_calls"] == probe["provider_boundaries"] == 0,
            "Full pinned native import-only preflight is missing")
    prefix = "/study/experiment/transfer_v9/upstream/rasa-" + RASA_PIN + "/rasa/"
    require(all(origin.startswith(prefix) if module != "telebot" else origin.startswith(
            "/study/experiment/transfer_v9/amendments/rasa_env/pydeps/telebot/")
            for module, origin in probe["origins"].items()), "Preflight imported another Rasa source or dependency package")
    for label in ("INSTALL", "PROBE"):
        process = read(env / (label + "_PROCESS.json"))
        require(process["returncode"] == 0 and IMAGE in process["command"]
                and process["command"][process["command"].index("--network") + 1] == "none"
                and process["auto_removed_after_exit"] is True, "Dependency install/probe process was not closed and isolated")
    operation = "rasa-telebot-dependency-install-and-import-preflight"
    settled = ledger["settles"].get(operation, {})
    require(settled.get("status") == "completed" and settled["evidence"]["dependency_receipt_sha256"] == sha(receipt_path)
            and settled["resources"]["end_to_end_seconds"] >= receipt["complete_setup_wall_seconds"]
            and all(settled["resources"][key] == 0 for key in COUNTS), "Dependency install/import setup cost was not retained in the original phase ledger")
    failed_setup = base / "engineering_retry2/development/rasa-workers/H/SETUP.json"
    require(amendment["stopped_setup_sha256"] == sha(failed_setup)
            and read(failed_setup)["receipt"]["message"] == "No module named 'telebot'", "Rasa startup incident was changed or omitted")
    failed_operation = ledger["settles"].get("development-rasa-startup-H", {})
    require(failed_operation.get("status") == "failed" and failed_operation["resources"]["end_to_end_seconds"] > 0,
            "Original failed CPU startup allocation was reset")
    roots = {"vanna": "engineering_retry2/development", "rasa": "engineering_rasa3/development"}
    require(amendment["completed_development_roots"] == roots
            and amendment["completed_development_operation_prefixes"] == {"vanna": "retry2-", "rasa": "retry3-"}, "Undeclared mixed development output roots")
    remaining = read(base / "RASA_REMAINING_DEVELOPMENT_FRAME.json")
    original = read(here / "cohorts/FRAME.json")["development"]["rasa"]
    require(remaining == [{**row, "operation_id": "retry3-" + row["operation_id"]} for row in original]
            and amendment["remaining_frame_sha256"] == sha(base / "RASA_REMAINING_DEVELOPMENT_FRAME.json"), "Remaining Rasa cases/criteria differ from original protocol")
    if completed or stage == "validation":
        gate = read(base / "DEVELOPMENT_GATE.json")
        require(gate["rasa_dependency_amendment_sha256"] == sha(amendment_path)
                and gate["completed_stage_roots"] == roots and gate["engineering_incidents_retained"] == 2,
                "Completed development gate hides its two engineering incidents")
    if stage == "development":
        context["frame"] = {"vanna": read(base / "ENGINEERING_RETRY_FRAME.json")["vanna"], "rasa": remaining}
        context["data_roots"] = {setting: safe(base, relative).parent for setting, relative in roots.items()}
        context["backend_root"] = context["data_roots"]["vanna"]
        context["worker_root"] = context["data_roots"]["rasa"]
        context["stopped"] = not completed
        require(completed or (base / "engineering_rasa3/STOP.json").exists(), "Rasa-only engineering continuation has not closed")
    context["rasa_setup_prefix"] = "rasa3-"
    context["dependency_receipt_sha256"] = sha(receipt_path)
    context["locked_dependency_addition"] = {"amendment_sha256": sha(amendment_path),
        "freeze_sha256": sha(freeze_path), "dependency_receipt_sha256": sha(receipt_path),
        "version": "4.7.0", "image_changed": False, "original_failed_cpu_startup_retained": True,
        "completed_vanna_queries_reacquired": 0}
    amendment_time = datetime.fromisoformat(freeze["at_utc"])
    require(all(datetime.fromisoformat(row["at_utc"]) >= amendment_time
                for ident, row in ledger["reserves"].items() if ident.startswith(("retry3-", "rasa3-"))),
            "Native Rasa continuation started before the locked dependency amendment froze")
    return context


def audit_stage(workspace, run, stage):
    workspace, run = Path(workspace).resolve(), Path(run).resolve()
    require(stage in ("development", "validation"), "Unknown closed stage")
    require(not (run / "accounting/WRITER_LOCK.json").exists(), "Refusing to audit an actively written campaign ledger")
    completed = (run / ("DEVELOPMENT_GATE.json" if stage == "development" else "NATIVE_BANK.json")).exists()
    stopped = (run / (stage.upper() + "_STOP.json")).exists()
    require(completed or stopped, "The requested acquisition stage has not closed")
    freeze = read(run / "STUDY_FREEZE.json")
    require(freeze["prior_receipt_sha256"] == PRIOR_SHA and freeze["guidance_sha256"] == GUIDANCE_SHA, "Immutable foundation mismatch")
    for relative, binding in freeze["files"].items():
        path = safe(workspace, relative)
        require(path.stat().st_size == binding["bytes"] and sha(path) == binding["sha256"], "Frozen source/data/config changed: " + relative)
    here = workspace / "experiment/transfer_v9"
    manifest_path = run / "RESOURCE_MANIFEST.json"
    require(manifest_path.read_bytes() == (run / "accounting/MANIFEST.json").read_bytes(), "Resource manifest changed")
    manifest = read(manifest_path)
    require(manifest["protocol_sha256"] == sha(run / "PROTOCOL.json"), "Resource caps belong to a different protocol")
    ledger = verify_ledger(manifest_path.read_bytes(), (run / "accounting/events.jsonl").read_bytes(), read(run / "accounting/HEAD.json"))
    reserves, settles = ledger["reserves"], ledger["settles"]
    context = engineering_context(workspace, run, stage, ledger, completed, stopped)
    context = rasa_dependency_context(workspace, run, stage, ledger, completed, context)
    data_root, stopped = context["data_root"], context["stopped"]
    data_roots = context.get("data_roots", {setting: data_root for setting in ("vanna", "rasa")})
    inventory = read(here / "screening/CASE_INVENTORY.json")
    bindings = source_bindings(workspace, inventory)
    source = here / ("upstream/rasa-" + RASA_PIN)
    closure = {path.relative_to(source).as_posix(): sha(path)
               for path in sorted((source / "rasa").rglob("*.py"))}
    require(len(closure) == 290 and digest(closure) == RASA_CLOSURE, "Actual full Rasa source closure differs from 290-file freeze")
    frame = context["frame"]
    planned = {row["operation_id"]: (setting, row) for setting in ("vanna", "rasa") for row in frame[setting]}
    require(len(planned) == (32 if stage == "development" else 256), "Unexpected prospective stage frame")
    live_normalized, live_descriptors = [], []
    if stage == "validation" and completed and not stopped:
        live_planned, live_normalized, live_descriptors = live_plan_frames(workspace, run)
        require(not set(live_planned).intersection(planned), "Live confirmation reused a recorded-bank operation")
        planned.update(live_planned)
    raw_paths = sorted({path for root in data_roots.values() for path in (root / stage / "raw").glob("*.json")})
    observations, incidents = {}, {}
    for path in raw_paths:
        raw = read(path)
        ident = raw["operation_id"]
        require(ident in planned and ident not in observations and ident not in incidents, "Unregistered or duplicate raw operation")
        if raw.get("schema") != "v9-native-observation-1":
            require(raw.get("status") == "study_incident", "Unknown raw record schema")
            require(ident in reserves, "Study incident lost its prior paid reservation")
            if ident in settles:
                require(settles[ident]["status"] in ("failed", "timed_out")
                        and settles[ident]["evidence"].get("incident_sha256") == sha(path), "Incident settlement/raw hash mismatch")
            incidents[ident] = raw
            continue
        setting, item = planned[ident]
        require(raw["frame"] == item and raw["setting_id"] == setting and raw["cohort"] == stage, "Raw/frame identity changed")
        require(raw["state_digest"] == expected_state_digest(here, setting, item["state"], stage, inventory,
                    context.get("dependency_receipt_sha256")),
                "Native code/input/config state commitment differs from actual registered sources")
        require(ident in reserves and ident in settles and settles[ident]["status"] == "completed", "Raw native result lacks a successful reservation/settlement")
        require(settles[ident]["evidence"].get("raw_sha256") == sha(path), "Settled native receipt SHA mismatch")
        resource_key = "native_query_units" if setting == "vanna" else "queryfree_native_check_units"
        require(reserves[ident]["resources"][resource_key] == 1 and settles[ident]["resources"][resource_key] == 1, "Wrong native accounting unit")
        require(reserves[ident]["metadata"]["task_id"] == item["task_id"] and reserves[ident]["metadata"]["state"] == item["state"], "Native ledger metadata differs from frozen frame")
        catalog = read(here / f"cohorts/{stage}/{setting}.private.json")
        tasks = {task["task_id"]: task for task in catalog["tasks"]}
        task, output = tasks[item["task_id"]], raw["native_output"]
        if setting == "vanna":
            independently_checked = independent_vanna(catalog, task, output)
            verify_vanna_methods(output, item["state"], bindings)
            dependencies = output["trace_tokens"]
            calls = raw["provider_call_ids"]
            require(1 <= len(calls) <= 3 and len(set(calls)) == len(calls), "Native Vanna SDK call ceiling/identity violation")
            for number, call in enumerate(calls, 1):
                require(call == f"{ident}-chat{number}" and call in reserves and call in settles, "Unjoined SDK boundary")
                request_path = data_roots["vanna"] / stage / "provider" / f"{call}-request.json"
                response_path = data_roots["vanna"] / stage / "provider" / f"{call}-response.json"
                require(settles[call]["evidence"].get("response_sha256") == sha(response_path), "SDK response hash differs from settlement")
                require(reserves[call]["metadata"]["parent_native_operation_id"] == ident, "SDK reservation points to a foreign native operation")
                verify_provider(read(request_path), read(response_path), call, ident, settles[call])
            require(sum(settles[call]["resources"]["generation_allocation_seconds"] for call in calls)
                    <= settles[ident]["resources"]["end_to_end_seconds"] + 1e-6,
                    "Nested SDK/model duration exceeds the whole native invocation interval")
        else:
            independently_checked = independent_rasa(task, output["output"])
            require(raw["provider_call_ids"] == [] and output["generative_provider_calls"] == 0, "Query-free native Rasa work was relabeled generation")
            require(output["task_id"] == item["task_id"] and output["operation_id"] == ident and output["status"] == "completed", "Native Rasa operation identity mismatch")
            require(output["task_input_sha256"] == digest(task["input"]), "Native Rasa received changed/extra task bytes")
            expected_form, expected_rank = ("parent" if item["state"] == "A" else "fixed",
                                            "parent" if item["state"] == "B" else "fixed")
            require(output["form_state"] == expected_form and output["ranking_state"] == expected_rank
                    and output["kind"] == task["kind"], "Native Rasa task historical source state changed")
            dependencies = ["code:" + path for path in output["trace"]["production_paths"]]
        require(independently_checked == raw["reference"], "Independent contract clauses disagree with the recorded reference")
        require(raw["reference_not_supplied_to_application_or_selector"] is True, "Reference separation declaration missing")
        for key in ("checker_seconds", "feature_seconds"):
            require(measured(raw[key]), "Invalid exclusive checker/feature duration")
        native = raw["outer_query_seconds_excluding_checker_feature"]
        require(measured(native, True), "Native duration missing")
        total = native + raw["checker_seconds"] + raw["feature_seconds"]
        require(math.isclose(total, settles[ident]["resources"]["end_to_end_seconds"], rel_tol=1e-9, abs_tol=1e-8), "Native/checker/feature timing components do not reconcile")
        inner_duration = output["native_seconds"] if setting == "vanna" else output["native_execution_seconds"]
        require(measured(inner_duration) and inner_duration <= native + 1e-6,
                "Inner native CPU/generation duration exceeds outer exclusive native interval")
        observations[ident] = {"path": path, "raw": raw, "setting": setting, "frame": item,
                               "dependencies": dependencies, "verdict": independently_checked}
    if completed and not stopped:
        require(set(observations) == set(planned) and not incidents, "Completed stage omits registered native observations")
    joined_calls = {call for item in observations.values() for call in item["raw"]["provider_call_ids"]}
    sdk_requests = {path.name.removesuffix("-request.json") for path in (data_roots["vanna"] / stage / "provider").glob("*-request.json")}
    sdk_responses = {path.name.removesuffix("-response.json") for path in (data_roots["vanna"] / stage / "provider").glob("*-response.json")}
    if completed and not stopped:
        require(sdk_requests == joined_calls == sdk_responses, "Omitted, reused or unjoined SDK request/response")
        ledger_calls = {ident for ident, row in reserves.items() if row["resources"]["provider_chat_units"]
                        and row.get("metadata", {}).get("parent_native_operation_id") in planned}
        require(ledger_calls == joined_calls, "Provider ledger includes a boundary omitted from raw results")
        require(not ledger["unsettled"] and not ledger["over_cap"] and not ledger["operation_overruns"],
                "Completed acquisition has unresolved reservations or resource overshoots")
    for ident, reservation in reserves.items():
        if reservation["resources"]["provider_chat_units"]:
            parent = reservation.get("metadata", {}).get("parent_native_operation_id")
            require(parent in reserves and reserves[parent]["resources"]["native_query_units"] == 1,
                    "Provider reservation has no paid native-generation parent")
    backend = context.get("backend_root", data_root) / stage / "backend"
    require((backend / "CLOSED.json").exists(), "Owned backend has not closed")
    closed, owner = read(backend / "CLOSED.json"), read(backend / "OWNER.json")
    require(closed["pid"] == owner["pid"] and closed["returncode"] is not None
            and closed["unrelated_processes_stopped"] is False, "Backend ownership/closure not established")
    command = owner["command"]
    for flag, value in (("--port", "33009"), ("--ctx-size", "4096"), ("--n-predict", "256"), ("--n-gpu-layers", "26")):
        require(flag in command and command[command.index(flag) + 1] == value, "Pinned backend configuration changed")
    require(all(flag in command for flag in ("--no-cache-prompt", "--no-warmup", "--offline")), "Backend cache/probe/offline configuration changed")
    original_assets = read(workspace / "experiment/runs/development_v8_20261101/backend/ASSET_RECHECK.json")
    actual_assets = read(backend / "ASSET_RECHECK.json")
    require(actual_assets["files"] == original_assets["files_verified"], "Pinned model/runtime asset commitments changed")
    executable = str(command[0]).replace("\\", "/").split("/")[-1]
    executable_assets = [row for row in actual_assets["files"] if str(row["path"]).replace("\\", "/").split("/")[-1] == executable]
    require(len(executable_assets) == 1 and executable_assets[0]["sha256"] == owner["executable_sha256"], "Model executable ownership/hash proof missing")
    startup = read(backend / "READY.json")
    startup_id = context["model_startup_id"]
    require(startup_id in settles and settles[startup_id]["status"] == "completed"
            and startup["owner_sha256"] == sha(backend / "OWNER.json")
            and startup["startup_generation_allocation_seconds"] == settles[startup_id]["resources"]["generation_allocation_seconds"]
            and startup["warmup_or_generation_probe"] is False, "Model startup/cost/ownership receipt mismatch")
    starts = backend_generation_starts((backend / "backend.log").read_text(encoding="utf-8", errors="replace"))
    if completed and not stopped:
        require(starts == len(joined_calls), "Actual backend generation starts do not equal joined SDK boundaries")
    rasa_setups = {}
    for path in sorted((context.get("worker_root", data_root) / stage / "rasa-workers").glob("*/SETUP.json")):
        setup = read(path)
        state = path.parent.name
        require((path.parent / "CLOSED.json").exists(), "Native CPU worker remains open")
        require(read(path.parent / "CLOSED.json")["process_returncode"] is not None, "Native CPU worker has not exited")
        ready, authority = setup["receipt"], setup["receipt"].get("source_authority", {})
        if ready.get("event") != "ready":
            require(stopped, "Completed acquisition contains a native CPU startup incident")
            continue
        if not stopped:
            require(read(path.parent / "CLOSED.json")["process_returncode"] == 0, "Completed native CPU worker exited with an error")
        require(ready.get("event") == "ready" and authority.get("source_closure_sha256") == RASA_CLOSURE
                and authority.get("source_python_file_count") == 290, "Full native source authority missing")
        body = {key: value for key, value in authority.items() if key != "authority_sha256"}
        require(authority.get("authority_sha256") == digest(body), "Native source authority hash changed")
        require(authority.get("inventory_sha256") == sha(here / "screening/CASE_INVENTORY.json"), "CPU source inventory changed")
        require(IMAGE in setup["command"] and setup["command"][setup["command"].index("--network") + 1] == "none"
                and "CUDA_VISIBLE_DEVICES=-1" in setup["command"], "CPU worker isolation/image changed")
        expected_states = {"RASA_FORM_TRIGGER": "parent" if state == "A" else "fixed",
                           "RASA_INTENT_RANKING": "parent" if state == "B" else "fixed"}
        for public, proof in authority["module_proofs"].items():
            cid = proof["case_id"]
            binding, _ = bindings[(cid, expected_states[cid], public)]
            require(proof["sha256"] == binding["sha256"] and proof["git_blob_sha1"] == binding["git_blob_sha1"]
                    and proof["state"] == expected_states[cid], "Native Rasa module differs from historical source")
        require(len(authority["module_proofs"]) == 3, "Native Rasa module proof omitted")
        expected_imports = {path[:-3].replace("/", "."): proof for path, proof in authority["module_proofs"].items()}
        require(ready["imported_module_proofs"] == expected_imports, "Imported CPU modules differ from selected historical source files")
        public_catalog = read(here / f"cohorts/{stage}/rasa.public.json")
        require(ready["catalog_sha256"] == sha(here / f"cohorts/{stage}/rasa.public.json")
                and ready["training_examples"] == len(public_catalog["training_examples"])
                and sorted(ready["trained_intent_classes"]) == sorted({row["intent"] for row in public_catalog["training_examples"]}),
                "Actual CPU training classes/examples differ from the frozen public training frame")
        operation = stage + "-rasa-startup-" + state
        operation = context.get("rasa_setup_prefix", "") + operation
        require(operation in settles and settles[operation]["status"] == "completed"
                and settles[operation]["evidence"]["setup_sha256"] == sha(path), "CPU setup cost receipt not joined")
        require(measured(setup["outer_setup_seconds"], True)
                and 0 <= ready["setup_and_training_seconds"] <= setup["outer_setup_seconds"] + 1e-6
                and setup["outer_setup_seconds"] <= settles[operation]["resources"]["end_to_end_seconds"] + 1e-6,
                "CPU native training/setup/outer accounting intervals do not nest")
        rasa_setups[state] = setup
    for item in observations.values():
        if item["setting"] == "rasa":
            output, state = item["raw"]["native_output"], item["frame"]["state"]
            require(state in rasa_setups, "Native task lacks its actual CPU resource setup")
            ready = rasa_setups[state]["receipt"]
            require(output["source_authority_sha256"] == ready["source_authority"]["authority_sha256"]
                    and output["catalog_sha256"] == ready["catalog_sha256"], "Native query/resource source or input mismatch")
    normalized_count = 0
    development_admission = None
    live_checked = []
    if completed and not stopped:
        normalized = read(run / "DEVELOPMENT_RECORDS.json") if stage == "development" else (
            read(run / "NATIVE_BANK.json")["records"] + read(run / "FRESH_CONFIRMATION.json")["records"] + live_normalized)
        ids, receipt_hashes = set(), set()
        for row in normalized:
            ident = row["record_id"]
            require(ident not in ids and row["receipt_sha256"] not in receipt_hashes, "Repeated normalized record/receipt identity")
            ids.add(ident)
            receipt_hashes.add(row["receipt_sha256"])
            require(ident in observations, "Normalized record does not join a raw native observation")
            item = observations[ident]
            require(safe(workspace, row["raw_path"]) == item["path"].resolve(), "Raw artifact path differs from registered normalized record")
            require(row["raw_sha256"] == row["receipt_sha256"] == sha(item["path"]), "Normalized native SHA binding changed")
            require(row["contract_pass"] == item["verdict"]["reference_pass"]
                    and row["observed_dependency_tokens"] == item["dependencies"], "Normalized reference or trace differs from actual raw execution")
            for key in ("checker_seconds", "feature_seconds"):
                require(row[key] == item["raw"][key], "Normalized exclusive CPU timing changed")
            require(row["elapsed_seconds"] == item["raw"]["outer_query_seconds_excluding_checker_feature"], "Normalized native timing changed")
            require(all(row[key] == item["frame"].get(key, 0) for key in ("task_id", "state", "case_id", "pass_index", "frame_role")), "Normalized/frame factorial identity mismatch")
        require(ids == set(observations), "Normalization omits actual native outputs")
        normalized_count = len(normalized)
        if stage == "validation":
            require(sum(row["frame_role"] == "primary_bank" and row["pass_index"] in (0, 1, 2) for row in normalized) == 192, "Incomplete primary frame")
            require(sum(row["frame_role"] == "fresh_confirmation" and row["pass_index"] == 3 for row in normalized) == 64, "Incomplete fresh confirmation frame")
            live_checked = audit_live_outcomes(live_descriptors, observations, reserves, settles)
            for bank_name in ("NATIVE_BANK.json", "FRESH_CONFIRMATION.json"):
                bank = read(run / bank_name)
                for setting in bank["settings"]:
                    expected_setup = (read(backend / "READY.json")["startup_generation_allocation_seconds"]
                        if setting["setting_id"] == "vanna" else sum(value["outer_setup_seconds"] for value in rasa_setups.values()))
                    require(setting["common_setup_seconds"] == expected_setup, "Shared setup allocation omitted or charged repeatedly")
                    for state, row in setting["states"].items():
                        require(row["state_digest"] == expected_state_digest(here, setting["setting_id"], state, stage, inventory,
                            context.get("dependency_receipt_sha256")),
                                "Normalized replay state commitment differs from the actual registered production bytes")
        else:
            gate = read(run / "DEVELOPMENT_GATE.json")
            expected_conditions = [{"operation_id": ident, "expected": planned[ident][1]["required_contract_pass"],
                "observed": observations[ident]["verdict"]["reference_pass"],
                "passed": observations[ident]["verdict"]["reference_pass"] == planned[ident][1]["required_contract_pass"]}
                for ident in planned]
            require({row["operation_id"]: row for row in gate["conditions"]} == {row["operation_id"]: row for row in expected_conditions}
                    and gate["passed"] == all(row["passed"] for row in expected_conditions), "Development admission was changed after outcomes")
            development_admission = gate["passed"]
    binding_names = ["STUDY_FREEZE.json", "PROTOCOL.json", "CASE_REGISTRY.json", "SOURCE_MANIFEST.json",
        "RESOURCE_MANIFEST.json", "accounting/MANIFEST.json", "accounting/events.jsonl", "accounting/HEAD.json",
        "ENGINEERING_AMENDMENT_FREEZE.json", "RASA_DEPENDENCY_AMENDMENT_FREEZE.json"]
    binding_names += (["DEVELOPMENT_RECORDS.json", "DEVELOPMENT_GATE.json", "DEVELOPMENT_RESOURCE_SUMMARY.json"]
                     if stage == "development" else ["NATIVE_BANK.json", "FRESH_CONFIRMATION.json",
                        "LIVE_POLICY_CONFIRMATION.json", "VALIDATION_RESOURCE_SUMMARY.json"])
    evidence_bindings = {(run / name).relative_to(workspace).as_posix(): sha(run / name)
                         for name in binding_names if (run / name).is_file()}
    return {"status": "PASS_COMPLETED_STAGE_INTEGRITY" if completed and not stopped else "PASS_RECORDED_STOP_INTEGRITY_ONLY",
        "at_utc": datetime.now(timezone.utc).isoformat(), "stage": stage,
        "auditor_source_sha256": sha(Path(__file__)),
        "evidence_bindings": evidence_bindings,
        "study_freeze_sha256": sha(run / "STUDY_FREEZE.json"), "complete_registered_frame": completed and not stopped,
        "native_observations_checked": len(observations), "planned_native_observations": len(planned),
        "incidents_retained": sorted(incidents), "normalized_records_checked": normalized_count,
        "development_admission_passed": development_admission,
        "fresh_live_policy_cells_checked": live_checked,
        "engineering_amendment_checked": context["amendment"],
        "locked_rasa_dependency_addition_checked": context.get("locked_dependency_addition"),
        "original_engineering_incidents_retained_separately": context["retained_original_incidents"],
        "joined_completed_sdk_boundaries": len(joined_calls), "actual_backend_generation_starts": starts,
        "source_bindings_checked": len(bindings), "rasa_cpu_resources_checked": sorted(rasa_setups),
        "ledger_events_checked": len(ledger["events"]), "ledger_committed_resources": ledger["totals"],
        "ledger_unsettled_operations_retained": ledger["unsettled"], "ledger_over_cap_dimensions": ledger["over_cap"],
        "native_or_provider_dispatches_during_audit": 0, "legacy_account_reopened": False,
        "independent_contract_checks": len(observations),
        "contracts_recomputed_independently": bool(observations),
        "independent_reference_sql_checks": sum(item["setting"] == "vanna" for item in observations.values()),
        "reference_sql_executed_in_separate_memory_database": any(item["setting"] == "vanna" for item in observations.values()),
        "original_host_method_path_fallback": False,
        "scientific_effectiveness_not_established_by_audit": True,
        "independent_applications_or_defects_added_by_audit": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--stage", choices=("development", "validation"), required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    code = 0
    try:
        result = audit_stage(args.workspace, args.run, args.stage)
    except (AuditError, KeyError, ValueError, OSError) as exc:
        result = {"status": "AUDIT_FAILED", "stage": args.stage,
                  "auditor_source_sha256": sha(Path(__file__)),
                  "exception_type": type(exc).__name__, "message": str(exc),
                  "native_or_provider_dispatches_during_audit": 0}
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

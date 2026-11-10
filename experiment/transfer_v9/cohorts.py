"""Prospective development/validation task bytes and public projections.

Generation is never imported or dispatched here. SQLite computes factual
reference rows directly from public fixture data, independently of native
Vanna execution or any model output. Rasa references are structural event and
ranking contracts. Neither these contracts nor screening labels enter a public
application projection. The task format and four historical mechanisms remain
the same across cohorts; different task bytes do not create new fault families.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


HERE = Path(__file__).resolve().parent
DATA = HERE / "cohorts"
COHORTS = ("development", "validation")
APPS = ("rasa", "vanna")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(obj, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def _check_ids(cohort, app):
    if cohort not in COHORTS or app not in APPS:
        raise ValueError("Unknown declared cohort/application")


def load_private(cohort, app):
    """Evaluator-only catalog; callers must not pass this to an application."""
    _check_ids(cohort, app)
    return _read(DATA / cohort / f"{app}.private.json")


def public_datasource(cohort):
    if cohort not in COHORTS:
        raise ValueError("Unknown declared cohort")
    return _read(DATA / cohort / "vanna.datasource.json")


def public_tasks(cohort, app):
    _check_ids(cohort, app)
    if app == "vanna":
        return _read(DATA / cohort / "vanna.tasks.public.json")["tasks"]
    return load_public_rasa(cohort)["tasks"]


def load_public_rasa(cohort):
    if cohort not in COHORTS:
        raise ValueError("Unknown declared cohort")
    return _read(DATA / cohort / "rasa.public.json")


def sqlite_references(catalog):
    """Use a separate in-memory SQLite source calculation, never native output."""
    result = {}
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute(catalog["schema"])
        connection.executemany("INSERT INTO transfers VALUES (?, ?, ?)", catalog["rows"])
        for task in catalog["tasks"]:
            query = task["reference_sql"]
            result[task["task_id"]] = [list(row) for row in connection.execute(query).fetchall()]
    return result


def _public_vanna(catalog):
    return ({key: copy.deepcopy(catalog[key]) for key in ("schema", "rows")},
            {"tasks": [{key: copy.deepcopy(task[key]) for key in ("task_id", "family", "question")}
                       for task in catalog["tasks"]]})


def _public_rasa(catalog):
    return {"application_id": "rasa", "training_examples": copy.deepcopy(catalog["training_examples"]),
            "tasks": [{key: copy.deepcopy(task[key]) for key in ("task_id", "kind", "input")}
                      for task in catalog["tasks"]]}


def construct_catalogs():
    """Construct both full cohorts before any development/native output."""
    validation_vanna = _read(HERE / "screening/VANNA_TASK_CATALOG.json")
    validation_rasa = _read(HERE / "screening/RASA_TASK_CATALOG.json")
    calculated = sqlite_references(validation_vanna)
    for task in validation_vanna["tasks"]:
        if task["expected_rows"] != calculated[task["task_id"]]:
            raise ValueError("Source Vanna reference does not match independent SQLite calculation")
        task["expected_rows"] = calculated[task["task_id"]]

    development_vanna = copy.deepcopy(validation_vanna)
    development_vanna["rows"] = [[11, "WITHIN", 45], [12, "WITHIN", 115], [13, "WITHIN", 70],
                                  [14, "OUTSIDE", 90], [15, "OUTSIDE", 20], [16, "OUTSIDE", 60]]
    questions = {
        "VS01": "Count the transfer records with status exactly WITHIN.",
        "VS02": "Calculate the sum of amounts for records with status exactly WITHIN.",
        "VS03": "Count transfer records whose status is exactly OUTSIDE.",
        "VS04": "Use a CTE named totals to calculate the sum of every transfer amount.",
        "VF01": "Draw a bar chart for transfer amounts summed by status.",
        "VF02": "Draw a scatter plot with transfer id on the x axis and amount on the y axis.",
        "VC01": "Give the total number of transfer records.",
        "VC02": "Find the maximum amount among all transfers.",
    }
    for task in development_vanna["tasks"]:
        task["question"] = questions[task["task_id"]]
        task["task_id"] = "DV" + task["task_id"]
    calculated = sqlite_references(development_vanna)
    for task in development_vanna["tasks"]:
        task["expected_rows"] = calculated[task["task_id"]]
        task["source"] += "; separate authored development data/questions, same source mechanism"

    development_rasa = copy.deepcopy(validation_rasa)
    replacements = {
        "RF01": {"form_name": "development_visit", "slot_name": "home_city", "entity_value": "Tokyo", "user_text": "I reside in Tokyo"},
        "RF02": {"form_name": "development_booking", "slot_name": "guest_count", "entity_value": 3, "user_text": "A reservation for three guests"},
        "RF03": {"form_name": "development_visit", "slot_name": "home_city", "prefilled_value": "Lisbon", "user_text": "Please continue the booking"},
        "RF04": {"form_name": "development_visit", "slot_name": "home_city", "entity_value": "Oslo", "user_text": "My home is in Oslo"},
        "RR01": {"text": "Where is my parcel delivery"},
        "RR02": {"text": "Please tell me the weather forecast"},
        "RR03": {"text": "hi there"},
        "RR04": {"text": "ciao"},
    }
    for task in development_rasa["tasks"]:
        original_id = task["task_id"]
        task["input"].update(replacements[original_id])
        if task["kind"] == "form":
            task["contract"]["slot_value"] = (task["input"]["entity_value"] if task["input"]["include_entity"]
                                                else task["input"]["prefilled_value"])
        task["task_id"] = "DV" + original_id
        task["provenance"]["source_description"] += "; separate development identity/input, same source mechanism"

    catalogs = {"development": {"vanna": development_vanna, "rasa": development_rasa},
                "validation": {"vanna": validation_vanna, "rasa": validation_rasa}}
    for cohort, apps in catalogs.items():
        for app, catalog in apps.items():
            catalog["cohort_id"] = cohort
            catalog["catalog_role"] = ("separate configuration development; never policy effectiveness validation" if cohort == "development"
                                        else "fresh precommitted validation task bytes; no native output seen during construction")
            catalog["same_historical_fault_families_across_cohorts"] = True
            catalog["independent_native_defect_count"] = 2
            catalog["reference_origin"] = ("separate in-memory SQLite evaluation of source-grounded reference SQL" if app == "vanna"
                                            else "upstream dialogue-mapping and global-ranking invariants; no intent-accuracy assumption")
    return catalogs


def construct_frames(catalogs):
    result = {"schema": "transfer-v9-prospective-cohort-frame-1", "application_order": list(APPS),
              "guidance_tuning_using_development": False, "fresh_confirmation_registered_before_primary_outputs": True,
              "development": {}, "validation": {}, "confirmation": {}}
    cases = {"vanna": ("VANNA_SQL_WITHIN", "VANNA_ASK_FIGURE"),
             "rasa": ("RASA_FORM_TRIGGER", "RASA_INTENT_RANKING")}
    for app in APPS:
        dev_tasks = catalogs["development"][app]["tasks"]
        val_ids = [task["task_id"] for task in catalogs["validation"][app]["tasks"]]
        case_a, case_b = cases[app]
        dev_a = [task["task_id"] for task in dev_tasks if (task.get("family") == "sql" if app == "vanna" else task["kind"] == "form")]
        dev_b = [task["task_id"] for task in dev_tasks if task["task_id"] not in dev_a]
        assert len(dev_a) == len(dev_b) == 4
        def source_case(task):
            return task["case"] if app == "vanna" else task["provenance"]["case_id"]
        def affected(task):
            return task["expected_affected_by"] if app == "vanna" else task["provenance"]["expected_affected_by"]
        for case_id, ids in ((case_a, dev_a), (case_b, dev_b)):
            selected = [task for task in dev_tasks if task["task_id"] in ids]
            assert sum(bool(affected(t)) for t in selected) == 2
            assert all(source_case(t) == case_id for t in selected)
        result["development"][app] = {"passes": 1, "slots": [
            {"case_id": "COMMON_HEALTHY", "state": "HEALTHY", "task_ids": [task["task_id"] for task in dev_tasks]},
            {"case_id": case_a, "state": "A_BAD", "task_ids": dev_a},
            {"case_id": case_b, "state": "B_BAD", "task_ids": dev_b}], "native_request_count": 16,
            "admission": {"healthy_pass_required": 8, "healthy_total": 8, "affected_failure_required_per_bad_state": 2,
                          "unaffected_control_pass_required_per_bad_state": 2, "failed_witness_or_control_is_retained": True}}
        slots = [{"case_id": case_id, "state": state, "task_ids": val_ids[:]}
                 for case_id, bad in ((case_a, "A_BAD"), (case_b, "B_BAD")) for state in ("HEALTHY", bad)]
        result["validation"][app] = {"passes": 3, "slots": copy.deepcopy(slots), "native_request_count": 96,
                                      "entire_setting_catalog_in_every_case_state": True}
        result["confirmation"][app] = {"passes": 1, "slots": copy.deepcopy(slots), "native_request_count": 32,
                                        "conditional_on_favorable_primary_result": False}
    result["totals"] = {"development_native_requests": 32, "primary_validation_native_requests": 192,
                        "fresh_confirmation_native_requests": 64, "core_native_requests": 288,
                        "vanna_core_native_requests": 144, "rasa_core_native_requests": 144,
                        "independent_upstream_cases": 4, "unique_defects_not_multiplied_by_slots_or_passes": True,
                        "anticipated_vanna_chat_requests_if_one_sql_and_one_plot_call": 180,
                        "vanna_chat_upper_bound_at_three_per_native_request": 432,
                        "rasa_llm_generation_requests": 0}
    result["interpretation"] = [
        "Frame counts are fixed planning counts, not completed observations.",
        "Healthy requests for cases A and B are physically separate registered acquisitions even when source/configuration bytes agree.",
        "Development and validation differ in task bytes and Vanna database values, while task format and historical mechanisms remain shared.",
        "Rasa training examples are the same public 12-intent reproduction frame; ranking contracts do not estimate language-understanding accuracy.",
        "Fresh confirmation repeats the fixed cases and creates no new independent application or defect sample.",
        "Model-boundary and native request counters differ; any probes, failures, or development extensions need explicit separate reservations.",
    ]
    return result


def construct_collector_frame(catalogs, plan):
    """Flat dispatcher rows; every operation has a fixed prospective identity."""
    frame = {"schema": "transfer-v9-collector-frame-1", "development": {}, "validation": {},
             "counts": copy.deepcopy(plan["totals"])}
    state_alias = {"HEALTHY": "H", "A_BAD": "A", "B_BAD": "B"}
    for app in APPS:
        tasks = {task["task_id"]: task for task in catalogs["development"][app]["tasks"]}
        dev_rows = []
        case_a = plan["development"][app]["slots"][1]["case_id"]
        for slot in plan["development"][app]["slots"]:
            state = state_alias[slot["state"]]
            # The common healthy frame is anchored to the actual A case ID;
            # both production mechanisms are fixed in this shared state.
            case_id = case_a if slot["case_id"] == "COMMON_HEALTHY" else slot["case_id"]
            for task_id in slot["task_ids"]:
                task = tasks[task_id]
                affected = task["expected_affected_by"] if app == "vanna" else task["provenance"]["expected_affected_by"]
                dev_rows.append({"operation_id": f"dev-{app}-{state}-{task_id}", "task_id": task_id,
                                 "state": state, "case_id": case_id, "pass_index": 0, "frame_role": "development",
                                 "required_contract_pass": state == "H" or case_id not in affected})
        frame["development"][app] = dev_rows
        validation_rows = []
        for pass_index in range(4):
            role = "primary_bank" if pass_index < 3 else "fresh_confirmation"
            for slot in plan["validation"][app]["slots"]:
                state, case_id = state_alias[slot["state"]], slot["case_id"]
                for task_id in slot["task_ids"]:
                    validation_rows.append({"operation_id": f"val-{app}-{case_id.lower()}-{state}-p{pass_index}-{task_id}",
                                            "task_id": task_id, "state": state, "case_id": case_id,
                                            "pass_index": pass_index, "frame_role": role})
        frame["validation"][app] = validation_rows
    return frame


def build():
    catalogs = construct_catalogs()
    frames = construct_frames(catalogs)
    written = []
    for cohort in COHORTS:
        for app in APPS:
            path = DATA / cohort / f"{app}.private.json"
            _write_new(path, catalogs[cohort][app]); written.append(path)
        datasource, tasks = _public_vanna(catalogs[cohort]["vanna"])
        for name, obj in (("vanna.datasource.json", datasource), ("vanna.tasks.public.json", tasks),
                          ("rasa.public.json", _public_rasa(catalogs[cohort]["rasa"]))):
            path = DATA / cohort / name
            _write_new(path, obj); written.append(path)
    frame_path = DATA / "FRAME_PLAN.json"
    _write_new(frame_path, frames); written.append(frame_path)
    dispatcher_path = DATA / "FRAME.json"
    _write_new(dispatcher_path, construct_collector_frame(catalogs, frames)); written.append(dispatcher_path)
    manifest = {"schema": "transfer-v9-cohort-byte-manifest-1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "created_before_development_native_outputs": True, "created_before_validation_native_outputs": True,
                "guidance_rules_changed": False, "source_screening_catalogs": {
                    app: {"path": f"screening/{app.upper()}_TASK_CATALOG.json", "sha256": _sha(HERE / f"screening/{app.upper()}_TASK_CATALOG.json")}
                    for app in APPS},
                "files": {path.relative_to(HERE).as_posix(): {"sha256": _sha(path), "bytes": path.stat().st_size} for path in written},
                "no_model_or_native_requests_from_this_builder": True}
    _write_new(DATA / "COHORT_MANIFEST.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", required=True)
    parser.parse_args()
    manifest = build()
    print(json.dumps({"manifest": str(DATA / "COHORT_MANIFEST.json"), "files": len(manifest["files"]),
                      "new_native_or_model_calls": 0}))


if __name__ == "__main__":
    main()

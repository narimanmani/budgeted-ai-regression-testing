"""Offline structural admission for v9; this never dispatches a native request.

Passing this validator establishes internal protocol/registry consistency, not
that an adapter exercises a full application or that a scientific claim holds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

GUIDANCE_SHA256 = "f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989"
GUIDANCE_FREEZE_SHA256 = "92e6d36aa3dd29d10ad06ca040d138a2ea73504a7aa15e981af474460f4b79d9"
PRIOR_RECEIPT_SHA256 = "c6f1612ee8ce6a72c10020007d0e73d50a4da0ff5dae9d68ca4851520f3b2004"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
METHODS = {"seeded_random", "cost_only", "impact_only",
           "history_only", "always_combined", "CG1", "budgeted_retest_all"}
OLD_SETTINGS = {"anythingllm", "librechat", "openwebui", "dify"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _positive_int(value):
    return type(value) is int and value > 0


def planned_counts(protocol):
    """Counts are planning counts, never measurements or independent samples."""
    bank = protocol["native_bank"]
    replay = protocol["replay"]
    cells = (bank["settings"] * bank["upstream_case_pairs_per_setting"]
             * bank["tasks_per_setting"] * bank["states_per_case_pair"])
    trajectories = (bank["settings"] * len(replay["sequences"])
                    * len(replay["impact_levels"])
                    * len(replay["operational_checker_levels"])
                    * len(replay["end_to_end_budget_native_request_units"])
                    * len(replay["methods"]) * replay["recorded_outcome_passes"])
    primary = cells * bank["passes_per_cell"]
    confirmation = cells * bank["fresh_confirmation_passes_per_cell"]
    live = protocol["native_policy_confirmation"]
    live_ceiling = live["settings"] * (live["cg1_native_requests_max_per_cell"]
                                      + live["retest_all_native_requests_per_cell"])
    development = protocol["development_request_ceiling"]
    cap = protocol["new_phase_resources"]["native_component_request_cap"]
    return {
        "registered_upstream_cases_target": bank["settings"] * bank["upstream_case_pairs_per_setting"],
        "native_primary_request_plan": primary,
        "native_confirmation_request_plan": confirmation,
        "native_bank_request_plan": primary + confirmation,
        "native_live_policy_confirmation_ceiling": live_ceiling,
        "development_request_ceiling": development,
        "native_core_request_plan": primary + confirmation + live_ceiling,
        "native_total_registered_request_ceiling": primary + confirmation + live_ceiling + development,
        "native_cap": cap,
        "native_contingency_requests": cap - primary - confirmation - live_ceiling - development,
        "counterfactual_trajectories": trajectories,
        "counterfactual_decisions": trajectories * replay["episodes_per_sequence"],
        "replay_cells_are_not_additional_native_requests": True,
        "replay_cells_are_not_independent_defects": True,
    }


def validate_design(protocol, registry, workspace=None, verify_bytes=False):
    errors, warnings = [], []
    def require(condition, message):
        if not condition:
            errors.append(message)

    required_sections = {"guidance", "legacy", "new_phase_resources", "native_bank", "native_policy_confirmation",
                         "replay", "costs", "analysis", "coverage_gates", "stopping"}
    missing = required_sections - set(protocol)
    if missing:
        return {"status": "BLOCKED", "errors": [f"Missing protocol sections: {sorted(missing)}"],
                "warnings": [], "planned_counts": None, "claims_permitted": {}}
    guide, legacy, resource = protocol["guidance"], protocol["legacy"], protocol["new_phase_resources"]
    bank, replay = protocol["native_bank"], protocol["replay"]
    costs, analysis = protocol["costs"], protocol["analysis"]
    require(guide.get("sha256") == GUIDANCE_SHA256, "Original CG1 bytes must remain pinned")
    require(guide.get("freeze_sha256") == GUIDANCE_FREEZE_SHA256, "Original CG1 freeze must remain pinned")
    require(guide.get("change_after_outcomes") is False, "CG1 may not be tuned after validation outcomes")
    require(legacy.get("receipt_sha256") == PRIOR_RECEIPT_SHA256, "Prior closed receipt binding differs")
    require(legacy.get("closed_native_count") == 4938 and legacy.get("closed_native_cap") == 5000,
            "Do not reset or expand the closed 4938/5000 legacy campaign")
    require(legacy.get("reset_or_increase_legacy_caps") is False, "Legacy caps must remain closed")
    gen_cap = resource.get("new_llm_generation_request_cap")
    require(type(gen_cap) is int and gen_cap >= 0,
            "New LLM generation allowance must be an explicit nonnegative integer")
    if type(gen_cap) is int and gen_cap > 0:
        gen_seconds = resource.get("new_generation_allocation_seconds_cap")
        require(type(gen_seconds) in (int, float) and gen_seconds > 0,
                "A model-enabled extension must declare its new generation-allocation time cap")
        require(resource.get("new_provider_meter_separate_from_closed_legacy") is True,
                "Model-enabled new work needs a new metered account; do not reopen closed legacy counters")
        require(resource.get("new_model_runtime_pinned_and_frozen") is True,
                "Model runtime and generation settings must be pinned before validation")
    require(resource.get("paid_services_allowed") is False, "No paid service is part of this protocol")
    require(resource.get("all_failed_attempts_and_probes_count") is True, "Failed attempts and probes must count")
    require(resource.get("legacy_native_unit_equivalence_assumed") is False,
            "Native component calls must not be silently equated with legacy generation units")
    require(resource.get("carry_legacy_counts_as_separate_closed_account") is True, "Carry the closed prior account")
    live = protocol["native_policy_confirmation"]
    require(live.get("registered_before_first_validation_output") is True,
            "Fresh live policy confirmation must be registered before validation outputs")
    require(live.get("source_case_key") == "A" and live.get("source_case_choice_uses_policy_scores") is False,
            "The ordinal A case must be chosen prospectively, not using policy scores")
    require(live.get("settings") == 2 and live.get("methods") == ["CG1", "budgeted_retest_all"],
            "Register the four fixed setting-by-method live confirmation cells")
    require(live.get("initial_history") == "cold_empty" and live.get("episodes_per_cell") == 1,
            "The native confirmation is only one cold A introduction per method/setting")
    require(live.get("request_ceiling_per_cell") == 28
            and live.get("cg1_profile_requests_per_cell") == 24
            and live.get("cg1_max_selected_pairs") == 2
            and live.get("cg1_native_requests_max_per_cell") == 28
            and live.get("retest_all_native_requests_per_cell") == 16,
            "Live confirmation accounting must retain paid profiles and the same 28-unit ceiling")
    require(live.get("queries_are_fresh_actual_native_requests") is True
            and live.get("bank_outcomes_reused_as_execution") is False
            and live.get("current_reference_or_new_outcome_to_selection") is False,
            "Native confirmation needs fresh execution with no current/future reference leakage")
    require(protocol.get("development_request_ceiling") == 32,
            "The finite development allowance must remain charged in the 400-unit new phase")

    integer_bank_keys = ("settings", "upstream_case_pairs_per_setting", "tasks_per_setting",
                         "states_per_case_pair", "passes_per_cell", "fresh_confirmation_passes_per_cell")
    numeric_valid = all(_positive_int(bank.get(key)) for key in integer_bank_keys)
    numeric_valid = numeric_valid and _positive_int(resource.get("native_component_request_cap"))
    numeric_valid = numeric_valid and _positive_int(replay.get("recorded_outcome_passes"))
    numeric_valid = numeric_valid and _positive_int(replay.get("episodes_per_sequence"))
    numeric_valid = numeric_valid and all(_positive_int(live.get(key)) for key in (
        "settings", "cg1_native_requests_max_per_cell", "retest_all_native_requests_per_cell"))
    numeric_valid = numeric_valid and _positive_int(protocol.get("development_request_ceiling"))
    require(numeric_valid, "All planned counts/caps must be positive integers, never booleans")
    require(bank.get("states_per_case_pair") == 2, "A historical case pair must bind both buggy and fixed states")
    require(bank.get("passes_per_cell") == 3, "Three native passes are required for the unchanged CG1 old-cost estimator")
    require(bank.get("freeze_before_first_validation_output") is True, "Freeze cases/code/masks before validation outputs")
    require(bank.get("reference_from_frozen_contract_not_majority_vote") is True,
            "Reference is the frozen contract, not majority vote on observed answers")
    require(bank.get("failed_source_cases_retained") is True and bank.get("replacement_after_policy_scores") is False,
            "Keep case attrition and forbid score-based replacement")
    require(set(replay.get("methods", [])) == METHODS and len(replay.get("methods", [])) == len(METHODS),
            "Report every registered fixed/simple/guidance arm exactly once")
    require(replay.get("native_execution_per_policy_cell_claimed") is False,
            "Counterfactual replay is not live native execution per policy cell")
    require(replay.get("history_source") == "strictly_earlier_own_selected_operational_pair_results",
            "History must contain only earlier own selected operational observations")
    for key in ("current_or_future_truth_to_selector", "selection_uses_true_failure_labels",
                "reference_outcomes_to_selector", "operational_error_mask_depends_on_truth",
                "impact_omission_depends_on_current_fault_outcomes"):
        require(replay.get(key) is False, f"Forbidden outcome/reference leakage: {key}")
    require(replay.get("masks_committed_before_bank_outputs") is True, "Error/omission masks must be prospective")
    require(replay.get("sequence_is_authored_intervention_order") is True,
            "Do not present constructed case sequences as actual maintenance chronology")
    require(replay.get("unique_defects_not_multiplied_by_repetition") is True,
            "Repeated trajectories do not create independent defects")
    for key in ("operational_error_probability", "impact_omission_probability"):
        value = replay.get(key)
        require(type(value) in (float, int) and 0 < value < 1, f"Invalid probability: {key}")
    budgets = replay.get("end_to_end_budget_native_request_units", [])
    require(isinstance(budgets, list) and len(budgets) >= 2
            and all(_positive_int(v) for v in budgets) and len(set(budgets)) == len(budgets),
            "At least two distinct fixed total-budget levels are required")
    require(costs.get("profile_old_requests_per_task_state") == 3,
            "CG1 uses exactly three charged old-state requests per task/state")
    for key in ("native_request_and_replayed_allocation_separate", "profile_cost_charged_only_to_consuming_method",
                "context_or_dependency_cost_charged_to_consuming_method", "failed_probes_and_acquisition_included",
                "resource_mask_changes_never_refund_already_paid_cost",
                "reference_research_costs_separate_from_deployable_policy_costs"):
        require(costs.get(key) is True, f"Missing complete-cost control: {key}")
    require(costs.get("profile_reuse_across_distinct_states") is False, "Profiles cannot be reused across different states")
    require(analysis.get("stop_on_winning_result") is False and analysis.get("success_requires_positive_gain") is False,
            "Completion must not depend on finding a positive result")
    require(analysis.get("simple_baseline_selected_using_validation_scores") is False,
            "Do not select a deployable simple baseline using held-out scores")
    require(analysis.get("uncertainty_unit_is_upstream_case_not_request") is True,
            "Uncertainty may not treat repeated requests as independent defects")

    settings, cases = registry.get("settings", []), registry.get("cases", [])
    require(isinstance(settings, list) and isinstance(cases, list), "Registry settings/cases must be lists")
    if not isinstance(settings, list) or not isinstance(cases, list):
        settings, cases = [], []
    require(len(settings) == bank.get("settings"), "Registered setting count differs from fixed plan")
    setting_ids = [x.get("setting_id") for x in settings]
    require(len(setting_ids) == len(set(setting_ids)) and all(setting_ids), "Setting identities must be distinct and nonempty")
    setting_by_id = {x.get("setting_id"): x for x in settings}
    for setting in settings:
        setting_id = setting.get("setting_id", "")
        canonical = re.sub("[^a-z0-9]", "", setting_id.lower())
        require(canonical not in OLD_SETTINGS, f"Previously used application is not untouched: {setting_id}")
        require(setting.get("native_boundary") in ("full_application", "native_component"),
                f"Declare full application versus native component boundary: {setting_id}")
        require(setting.get("previously_used_for_guidance_development") is False,
                f"Setting is not eligible for untouched-setting claim: {setting_id}")
        tasks = setting.get("validation_task_ids", [])
        require(isinstance(tasks, list) and len(tasks) == bank.get("tasks_per_setting") and len(set(tasks)) == len(tasks),
                f"Complete distinct public task catalog required: {setting_id}")
        own = [case for case in cases if case.get("setting_id") == setting_id]
        require(len(own) == bank.get("upstream_case_pairs_per_setting"), f"Case count differs from plan: {setting_id}")
        require(len({case.get("mechanism_id") for case in own}) >= protocol["coverage_gates"].get("minimum_distinct_mechanisms_per_setting", 2),
                f"Distinct upstream mechanisms are required: {setting_id}")
    ids = [case.get("case_id") for case in cases]
    require(len(ids) == len(set(ids)) and all(ids), "Upstream case IDs must be distinct and nonempty")
    artifacts = []
    for case in cases:
        cid = case.get("case_id", "missing-case-id")
        sid = case.get("setting_id")
        require(sid in setting_by_id, f"Unknown setting for case {cid}")
        for key in ("buggy_commit", "fixed_commit", "fix_parent_commit"):
            require(isinstance(case.get(key), str) and SHA40.fullmatch(case[key]) is not None,
                    f"Full pinned Git SHA required: {cid}/{key}")
        require(case.get("buggy_commit") != case.get("fixed_commit"), f"Buggy/fixed states are identical: {cid}")
        for key in ("upstream_repository_url", "upstream_change_url"):
            require(isinstance(case.get(key), str) and case[key].startswith("https://"), f"Upstream source URL required: {cid}/{key}")
        require(case.get("case_origin") in ("upstream_historical_bugfix", "documented_upstream_regression"),
                f"Case must have an independently sourced upstream origin: {cid}")
        direction = case.get("intervention_direction")
        require(direction in ("controlled_reintroduction", "natural_chronological_change"),
                f"Declare intervention direction: {cid}")
        if direction == "natural_chronological_change":
            require(case.get("case_origin") == "documented_upstream_regression", f"Natural regression requires upstream introduction evidence: {cid}")
            for key in ("introduced_commit", "healthy_parent_commit"):
                require(isinstance(case.get(key), str) and SHA40.fullmatch(case[key]) is not None,
                        f"Natural chronology requires {key}: {cid}")
        require(case.get("selection_used_policy_scores") is False, f"Case selected using validation policy scores: {cid}")
        for key in ("production_path", "entry_point", "upstream_contract_evidence", "license_path"):
            require(isinstance(case.get(key), str) and bool(case[key].strip()), f"Missing provenance/reachability field: {cid}/{key}")
        for key in ("contract_sha256", "source_manifest_sha256"):
            require(isinstance(case.get(key), str) and SHA64.fullmatch(case[key]) is not None,
                    f"Bound frozen bytes required: {cid}/{key}")
        if sid in setting_by_id:
            require(set(case.get("validation_task_ids", [])) == set(setting_by_id[sid].get("validation_task_ids", [])),
                    f"Every case state must execute the entire setting task catalog: {cid}")
        if case.get("contract_path"):
            artifacts.append((case["contract_path"], case.get("contract_sha256"), f"{cid}/contract"))
        else:
            require(False, f"An actual contract_path is required: {cid}")
        if case.get("source_manifest_path"):
            artifacts.append((case["source_manifest_path"], case.get("source_manifest_sha256"), f"{cid}/source_manifest"))
        else:
            require(False, f"An actual source_manifest_path is required: {cid}")

    freeze = registry.get("freeze", {})
    require(freeze.get("sealed_before_native_validation_outputs") is True, "Registry freeze is not sealed prospectively")
    require(freeze.get("all_required_bytes_available") is True, "Frozen closure must have all required bytes")
    require(freeze.get("no_validation_policy_scores_seen") is True, "Registry must precede validation policy scores")
    require(isinstance(freeze.get("manifest_sha256"), str) and SHA64.fullmatch(freeze["manifest_sha256"]) is not None,
            "Registry must bind an actual closure-manifest digest")
    if verify_bytes:
        require(workspace is not None, "Byte verification requires an explicit workspace root")
        if workspace is not None:
            root = Path(workspace).resolve()
            artifacts += [(guide.get("source", ""), GUIDANCE_SHA256, "guidance"),
                          (legacy.get("final_receipt", ""), PRIOR_RECEIPT_SHA256, "legacy_receipt")]
            for relative, expected, label in artifacts:
                path = root / relative
                try:
                    require(path.is_file() and sha256(path) == expected, f"Frozen byte binding failed: {label}")
                except OSError:
                    require(False, f"Cannot read frozen artifact: {label}")

    counts = None
    if numeric_valid:
        try:
            counts = planned_counts(protocol)
            require(counts["native_contingency_requests"] >= 0, "Fixed native plan exceeds new component-request cap")
        except (KeyError, TypeError):
            errors.append("Cannot calculate fixed-frame resource counts")
    complete_app = bool(settings) and all(x.get("native_boundary") == "full_application" for x in settings)
    if not complete_app:
        warnings.append("Component-level execution does not establish full application-level external validation")
    warnings.append("Replay contrasts remain conditional on this finite native observation bank")
    warnings.append("Four upstream cases cannot establish broad-population precision or TOSEM readiness")
    return {
        "status": "PASS_STRUCTURAL_ADMISSION" if not errors else "BLOCKED",
        "errors": errors, "warnings": warnings, "planned_counts": counts,
        "claims_permitted": {
            "source_registered_native_bank_ready": not errors,
            "native_component_scope_declared": not complete_app,
            "complete_application_level_external_validation_established": False,
            "portable_guidance_established": False,
            "full_three_way_interaction_established": False,
            "tosem_readiness_established": False,
        },
        "new_native_or_model_calls_from_this_validator": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--verify-bytes", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = validate_design(read_json(args.protocol), read_json(args.registry), args.workspace, args.verify_bytes)
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(output)
    print(output)
    raise SystemExit(0 if result["status"] == "PASS_STRUCTURAL_ADMISSION" else 2)


if __name__ == "__main__":
    main()

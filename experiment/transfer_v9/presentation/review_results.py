"""Post hoc, read-only interpretation tables and a retained background-case audit.

Uses the same completed-native-audit and closed-analysis gates as the initial
presenter. Writes a NEW directory; original presentation and experiment stay
unchanged. No model/native dispatch or reference-label replacement exists here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("v9_closed_presentation", Path(__file__).with_name("present_results.py"))
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def aggregate_primary(summary):
    groups = {}
    for cell in summary["matched_cells"]:
        identity = cell["identity"]
        if identity["analysis_frame"] != "primary":
            continue
        fields = ("setting_id", "request_budget", "impact_level", "checker_level", "method")
        key = tuple(identity[field] for field in fields)
        group = groups.setdefault(key, {"identity": dict(zip(fields, key)), "world_sequence_trajectories": 0,
                                       "totals": Counter(), "costs": Counter()})
        group["world_sequence_trajectories"] += len(cell["native_passes"])
        group["totals"].update(cell["totals"])
        group["costs"].update(cell["costs"])
    rows = []
    for key in sorted(groups):
        group = groups[key]
        totals, costs, worlds = group["totals"], group["costs"], group["world_sequence_trajectories"]
        rows.append({**group["identity"], "world_sequence_trajectories": worlds,
            "repeated_reference_opportunities": totals["reference_regression_opportunities"],
            "detected_repeated_opportunities": totals["detected_true_regressions"],
            "missed_repeated_opportunities": totals["missed_reference_regressions"],
            "reference_discordant_alarms": totals["reference_discordant_alarms"],
            "mean_allocated_native_requests": P._requests(costs) / worlds,
            "mean_profile_requests": costs["profile_requests"] / worlds,
            "mean_selected_requests": costs["selected_requests"] / worlds,
            "both_registered_case_orders_aggregated_descriptively": True,
            "independent_case_count_is_not_world_sequence_trajectories": True})
    return rows


def aggregate_contrasts(summary, field, values_field, keep_checker=True):
    fields = ["setting_id", "request_budget", "impact_level"] + (["checker_level"] if keep_checker else [])
    groups = {}
    for contrast in summary[field]:
        identity = contrast["identity"]
        if identity["analysis_frame"] != "primary":
            continue
        key = tuple(identity[name] for name in fields)
        row = groups.setdefault(key, {"identity": dict(zip(fields, key)), "values": Counter(), "case_orders": 0})
        row["values"].update(contrast[values_field])
        row["case_orders"] += 1
    return [{**row["identity"], **row["values"], "case_orders_summed": row["case_orders"],
             "finite_sequential_regime_contrast_not_population_causality": True}
            for _, row in sorted(groups.items())]


def background_case(workspace, run, audit, loaded):
    workspace, run = Path(workspace), Path(run)
    audit_obj = P.read_json(audit)
    fresh_path = run / "FRESH_CONFIRMATION.json"
    expected_fresh_sha = P._binding(audit_obj["evidence_bindings"], fresh_path, workspace)
    if P.sha(fresh_path) != expected_fresh_sha:
        raise P.PresentationError("Native-audited fourth-pass bank changed")
    primary = P.read_json(loaded["paths"]["native_bank"])
    fresh = P.read_json(fresh_path)
    records = primary["records"] + fresh["records"]
    for cell in loaded["values"]["live"]["cells"]:
        records += cell["records"]
    selected = {row["record_id"]: row for row in records
                if row["setting_id"] == "vanna" and row["task_id"] == "VS04"}
    if not selected:
        raise P.PresentationError("Named retained VS04 background case is absent")
    rows, errors, generated, finishes, completion_tokens = [], Counter(), Counter(), Counter(), Counter()
    for identity, record in sorted(selected.items()):
        raw_path = workspace / record["raw_path"]
        P._relative(raw_path, workspace)
        if P.sha(raw_path) != record["raw_sha256"]:
            raise P.PresentationError("Raw background-case receipt changed")
        raw = P.read_json(raw_path)
        error = raw["native_output"].get("error", {})
        errors[error.get("message")] += 1
        providers = []
        for call in raw["provider_call_ids"]:
            response_path = run / "validation/provider" / (call + "-response.json")
            request_path = run / "validation/provider" / (call + "-request.json")
            response, request = P.read_json(response_path)["response"], P.read_json(request_path)["payload"]
            choice = response["choices"][0]
            generated[choice["message"]["content"]] += 1
            finishes[choice["finish_reason"]] += 1
            completion_tokens[response["usage"]["completion_tokens"]] += 1
            providers.append({"provider_call_id": call, "response_sha256": P.sha(response_path),
                "request_sha256": P.sha(request_path), "finish_reason": choice["finish_reason"],
                "completion_tokens": response["usage"]["completion_tokens"], "max_tokens": request["max_tokens"],
                "reported_length_truncation": choice["finish_reason"] == "length"})
        rows.append({"record_id": identity, "case_id": record["case_id"], "state": record["state"],
            "frame_role": record["frame_role"], "reference_pass": record["contract_pass"],
            "raw_sha256": record["raw_sha256"], "native_error_type": error.get("type"),
            "native_error_message": error.get("message"), "provider_calls": providers})
    return {"status": "POST_HOC_RETAINED_BACKGROUND_FAILURE_DESCRIPTION",
        "target": "VS04", "native_observations": len(rows),
        "state_counts": dict(Counter(row["state"] for row in rows)),
        "all_observed_contract_outcomes_fail": all(row["reference_pass"] is False for row in rows),
        "error_messages": dict(errors), "generated_SQL_contents": dict(generated),
        "SDK_finish_reasons": dict(finishes), "SDK_completion_token_counts": dict(completion_tokens),
        "all_SDK_responses_terminate_with_stop": set(finishes) == {"stop"},
        "any_reported_length_truncation": any(p["reported_length_truncation"] for row in rows for p in row["provider_calls"]),
        "all_completion_tokens_below_frozen_maximum": all(p["completion_tokens"] < p["max_tokens"] for row in rows for p in row["provider_calls"]),
        "source_case_or_reference_labels_changed": False, "extra_independent_upstream_cases": 0,
        "interpretation": "A retained baseline generated-SQL functional failure across H/A/B; not a fifth independently sourced upstream defect or a new old-pass/new-fail change regression. The complete SQL omits FROM totals in its outer SELECT; stop termination below the ceiling does not support a length-truncation explanation. No oracle implementation error is established.",
        "native_audit_checks_raw_and_SDK_receipt_joins": True,
        "fresh_bank_sha256": expected_fresh_sha, "rows": rows}


def review(*, workspace, run, audit, readiness, output):
    loaded = P.closed_input_gate(workspace=workspace, run=run, audit=audit, readiness=readiness)
    summary = loaded["values"]["summary"]
    primary = aggregate_primary(summary)
    exact_balanced = [row for row in P.cell_rows(summary)
        if row["sequence_order"] == "mechanism_interleaved" and row["checker_level"] == "contract_exact"
        and row["impact_level"] == "observed_native_edges" and row["request_budget"] == 16 * row["horizon"]]
    tables = {
        "PRIMARY_AGGREGATED_OVER_TWO_CASE_ORDERS.csv": primary,
        "PRIMARY_OBSERVED_TRACES_EXACT_CHECKER.csv": [row for row in primary
            if row["impact_level"] == "observed_native_edges" and row["checker_level"] == "contract_exact"],
        "BALANCED_EXACT_OBSERVED_HIGH_ALLOWANCE_ALL_METHODS.csv": exact_balanced,
        "PRIMARY_FIXED_I_BY_H_SUMMED_OVER_ORDERS.csv": aggregate_contrasts(summary,
            "fixed_arm_impact_by_history_contrasts", "combined_minus_impact_minus_history_plus_cost"),
        "PRIMARY_CHECKER_MODERATION_SUMMED_OVER_ORDERS.csv": aggregate_contrasts(summary,
            "checker_moderation_of_fixed_arm_impact_by_history", "noisy_minus_exact_I_by_H_contrast", False),
    }
    background = background_case(workspace, run, audit, loaded)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in tables.items():
        P.write_csv(output / name, rows)
    (output / "RETAINED_VS04_BACKGROUND_FAILURE.json").write_text(json.dumps(background, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {"status": "COMPLETE_POST_HOC_READ_ONLY_REVIEW_DERIVATIVE",
        "source_sha256": P.sha(Path(__file__)), "presenter_source_sha256": P.sha(Path(__file__).with_name("present_results.py")),
        "audit_sha256": loaded["audit_sha256"], "readiness_sha256": loaded["readiness_sha256"],
        "input_sha256": loaded["input_sha256"], "native_or_model_calls": 0,
        "frozen_core_or_original_presentation_modified": False,
        "tables": {key: len(value) for key, value in tables.items()},
        "scope_notes": P.SCOPE_NOTES,
        "output_sha256": {path.name: P.sha(path) for path in sorted(output.iterdir()) if path.is_file()}}
    (output / "REVIEW_DERIVATIVE_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("workspace", "run", "audit", "readiness", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    result = review(**vars(args))
    print(json.dumps({key: result[key] for key in ("status", "native_or_model_calls", "tables")}, indent=2))


if __name__ == "__main__":
    main()

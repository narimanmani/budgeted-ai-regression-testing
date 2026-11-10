"""Post-freeze v9 presentation derivative; audited closed inputs only.

This file contains no native/model dispatch. It never mutates experimental
records, frozen code, admission criteria, the paper, or the sealed report.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re


class PresentationError(ValueError):
    pass


METHOD_ORDER = ("seeded_random", "cost_only", "impact_only", "history_only",
                "always_combined", "CG1", "budgeted_retest_all")
SCOPE_NOTES = [
    "Four independently sourced historical bug/fix mechanisms; authored interventions over two pinned native-path settings.",
    "The 672 primary counterfactual trajectories and repeated task-change opportunities are not independent defects or live policy runs.",
    "Four fresh live cells cover only the first A change, empty history, exact contracts and a 28-request ceiling; they do not test long history or noisy checking live.",
    "The checker-noise and edge-omission masks are controlled authored perturbations with probability 0.25, not estimates of naturally occurring error rates.",
    "Constructed sequences repeatedly revisit the SAME two fault/repair states. Exact H/A/B profile reuse is an optimistic recurrence scenario, NOT amortization over unseen new versions.",
    "Only interleaved 4/8/16 prefixes balance the two cases. Blocked 4/8 prefixes contain A only, whereas blocked16 includes A+B; their horizon comparison confounds case composition.",
    "Fixed I-by-H differences and judgment moderation describe finite recorded-outcome sequential regimes, not population causal effects.",
    "Budgets match native request allowances, not wall time. Recorded native wall, controller CPU and their explicitly labeled hybrid proxy remain distinct.",
    "Native-path execution is not complete application-level external validation or a guarantee of portable guidance or TOSEM readiness.",
]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _relative(path, workspace):
    try:
        return Path(path).resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError as exc:
        raise PresentationError("Presentation input must remain inside the declared workspace") from exc


def _binding(mapping, path, workspace):
    relative = _relative(path, workspace)
    normalized = {str(key).replace("\\", "/").lower(): value for key, value in mapping.items()}
    value = normalized.get(relative.lower())
    if not _is_sha(value):
        raise PresentationError("Missing exact input byte binding: " + relative)
    return value


def closed_input_gate(*, workspace, run, audit, readiness, summary=None, protocol=None):
    """Read status/closure gates BEFORE opening any experimental result bytes."""
    run, workspace = Path(run), Path(workspace)
    audit, readiness = Path(audit), Path(readiness)
    audit_data = read_json(audit)
    if (audit_data.get("status") != "PASS_COMPLETED_STAGE_INTEGRITY"
            or audit_data.get("stage") != "validation"
            or audit_data.get("complete_registered_frame") is not True
            or audit_data.get("native_or_provider_dispatches_during_audit") != 0):
        raise PresentationError("Independent completed-validation audit has not passed")
    gate = read_json(readiness)
    if gate.get("status") != "PASS" or gate.get("all_owned_helpers_closed") is not True:
        raise PresentationError("Native execution/helpers are not independently declared closed for analysis")
    bindings = gate.get("bound_files_sha256")
    if not isinstance(bindings, dict):
        raise PresentationError("Analysis readiness lacks exact result-file bindings")
    audit_expected = _binding(bindings, audit, workspace)
    if sha(audit) != audit_expected:
        raise PresentationError("Analysis readiness binds a different independent audit")
    paths = {
        "summary": Path(summary) if summary else run / "evaluation/SUMMARY.json",
        "protocol": Path(protocol) if protocol else run / "PROTOCOL.json",
        "native_bank": run / "NATIVE_BANK.json",
        "live": run / "LIVE_POLICY_CONFIRMATION.json",
        "resource": run / "VALIDATION_RESOURCE_SUMMARY.json",
    }
    expected = {role: _binding(bindings, path, workspace) for role, path in paths.items()}
    # All bindings have been found before any result is opened, even for hashing.
    for role, path in paths.items():
        if sha(path) != expected[role]:
            raise PresentationError("Closed presentation input changed: " + role)
    native_audit_bindings = audit_data.get("evidence_bindings", {})
    for role in ("protocol", "native_bank", "live", "resource"):
        if _binding(native_audit_bindings, paths[role], workspace) != expected[role]:
            raise PresentationError("Native audit and derivative readiness disagree: " + role)
    values = {role: read_json(paths[role]) for role in ("summary", "live", "resource")}
    if (values["summary"].get("bank_sha256") != expected["native_bank"]
            or values["summary"].get("protocol_sha256") != expected["protocol"]):
        raise PresentationError("Replay summary is not derived from the native-audited bank/protocol")
    if values["summary"].get("status") != "COMPLETE_RECORDED_OUTCOME_REPLAY":
        raise PresentationError("Replay did not complete its registered frame")
    return {"values": values, "paths": paths, "input_sha256": expected,
            "audit_sha256": audit_expected, "readiness_sha256": sha(readiness),
            "audit_status": audit_data["status"], "audit_path": _relative(audit, workspace),
            "readiness_path": _relative(readiness, workspace)}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _requests(costs):
    return costs.get("profile_requests", 0) + costs.get("selected_requests", 0)


def cell_rows(summary):
    rows = []
    for cell in summary.get("matched_cells", []):
        identity, totals, costs = cell["identity"], cell["totals"], cell["costs"]
        worlds = len(cell.get("native_passes", []))
        if worlds != 3 or identity.get("method") not in METHOD_ORDER:
            raise PresentationError("Matched cell lacks the three registered worlds or a registered method")
        regressions = totals.get("reference_regression_opportunities", 0)
        detections = totals.get("detected_true_regressions", 0)
        rows.append({**identity, "recorded_worlds": worlds,
            "repeated_reference_opportunities": regressions,
            "detected_repeated_opportunities": detections,
            "missed_repeated_opportunities": totals.get("missed_reference_regressions", 0),
            "detection_fraction": _ratio(detections, regressions),
            "reference_discordant_alarms": totals.get("reference_discordant_alarms", 0),
            "repair_alarms": totals.get("repair_alarms", 0),
            "controlled_endpoint_flips": totals.get("controlled_endpoint_flips", 0),
            "endpoint_judgments": totals.get("endpoint_judgments", 0),
            "realized_flip_fraction_in_selected_endpoints": _ratio(totals.get("controlled_endpoint_flips", 0), totals.get("endpoint_judgments", 0)),
            "allocated_requests_sum_of_three_worlds": _requests(costs),
            "mean_allocated_requests_per_world": _requests(costs) / worlds,
            "profile_requests_sum_of_three_worlds": costs.get("profile_requests", 0),
            "selected_requests_sum_of_three_worlds": costs.get("selected_requests", 0),
            "mean_profile_requests_per_world": costs.get("profile_requests", 0) / worlds,
            "mean_selected_requests_per_world": costs.get("selected_requests", 0) / worlds,
            "mean_recorded_native_wall_allocation_seconds_per_world": costs.get("total_allocated_wall_seconds", 0) / worlds,
            "mean_measured_controller_decision_cpu_seconds_per_world": costs.get("decision_cpu_seconds", 0) / worlds,
            "mean_measured_operational_mask_cpu_seconds_per_world": costs.get("operational_mask_cpu_seconds", 0) / worlds,
            "mean_native_wall_plus_controller_cpu_HYBRID_PROXY_seconds_per_world": costs.get("total_allocated_native_wall_plus_controller_cpu_proxy_seconds", 0) / worlds,
            "horizon_composition": ("balanced_two_cases" if identity["sequence_order"] == "mechanism_interleaved"
                else "A_only" if identity["horizon"] < 16 else "A_and_B"),
            "actual_native_policy_execution": False})
    return rows


def live_rows(live):
    if (live.get("schema") != "v9-live-policy-confirmation-1" or live.get("cells_planned") != 4
            or live.get("matched_native_request_ceiling_per_cell") != 28
            or live.get("long_history_or_noisy_checker_live_claimed") is not False):
        raise PresentationError("Unexpected live confirmation design")
    cells = live.get("cells", [])
    keys = {(cell.get("setting_id"), cell.get("method")) for cell in cells}
    if len(cells) != 4 or len(keys) != 4:
        raise PresentationError("Four distinct registered live setting/method cells are required")
    rows = []
    for cell in cells:
        if (cell.get("physically_executed_not_counterfactual_replay") is not True
                or cell.get("initial_history") != "empty"
                or cell.get("native_request_ceiling") != 28
                or cell.get("operational_checker") != "exact frozen contract"):
            raise PresentationError("Live confirmation boundary changed")
        total = cell["actual_total_native_requests"]
        if (total != cell["actual_profile_native_requests"] + cell["actual_selected_native_requests"]
                or total > 28 or cell["unused_native_request_allowance"] != 28 - total):
            raise PresentationError("Live request accounting does not reconcile")
        rows.append({"setting_id": cell["setting_id"], "method": cell["method"], "case_id": cell["case_id"],
            "native_request_ceiling": 28, "actual_profile_native_requests": cell["actual_profile_native_requests"],
            "actual_selected_native_requests": cell["actual_selected_native_requests"],
            "actual_total_native_requests": total, "unused_native_request_allowance": 28 - total,
            "observed_contract_regression_pairs_IN_THIS_SELECTED_LIVE_CELL": cell["observed_contract_regression_pairs"],
            "selected_task_ids": ";".join(cell["selected_task_ids"]),
            "allocated_native_and_checker_feature_wall_seconds": cell["allocated_native_and_checker_feature_wall_seconds"],
            "controller_cpu_seconds": cell["controller_cpu_seconds"],
            "scope": "first_A_change_only_cold_exact_checker",
            "recall_denominator_borrowed_from_other_cell": False})
    return sorted(rows, key=lambda row: (row["setting_id"], row["method"]))


def comparison_rows(summary):
    rows = []
    for comparison in summary.get("cg1_comparisons", []):
        if comparison["identity"].get("analysis_frame") != "primary":
            continue
        rows.append({**comparison["identity"], "baseline": comparison["baseline"],
            **{key: comparison[key] for key in ("cg1_minus_baseline_detections",
                "cg1_minus_baseline_discordant_alarms", "cg1_minus_baseline_allocated_requests")}})
    return rows


def case_comparison_rows(summary):
    rows = []
    for comparison in summary.get("cg1_comparisons", []):
        if comparison["identity"].get("analysis_frame") != "primary":
            continue
        for case, values in comparison.get("by_upstream_case", {}).items():
            rows.append({**comparison["identity"], "baseline": comparison["baseline"], "upstream_case_id": case, **values})
    return rows


def contrast_rows(summary):
    rows = []
    for row in summary.get("fixed_arm_impact_by_history_contrasts", []):
        if row["identity"].get("analysis_frame") == "primary":
            rows.append({**row["identity"], **row["combined_minus_impact_minus_history_plus_cost"],
                "contrast": "combined - impact_only - history_only + cost_only",
                "finite_recorded_regimes_not_population_causality": True})
    return rows


def moderation_rows(summary):
    rows = []
    for row in summary.get("checker_moderation_of_fixed_arm_impact_by_history", []):
        if row["identity"].get("analysis_frame") == "primary":
            rows.append({**row["identity"], **row["noisy_minus_exact_I_by_H_contrast"],
                "contrast": "noisy_checker_I_by_H - exact_checker_I_by_H",
                "population_oracle_accuracy_estimated": False})
    return rows


def resource_rows(value, prefix=""):
    rows = []
    sensitive = ("api_key", "password", "secret", "credential", "authorization", "bearer", "access_token")
    if isinstance(value, dict):
        for key, child in sorted(value.items()):
            if not any(term in key.lower() for term in sensitive):
                rows += resource_rows(child, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        rows.append({"resource_field": prefix, "value": value})
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows += resource_rows(child, f"{prefix}[{index}]")
    return rows


def write_csv(path, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def make_tables(summary, live, resource):
    all_rows = cell_rows(summary)
    primary = [row for row in all_rows if row["analysis_frame"] == "primary"]
    balanced = [row for row in all_rows if row["sequence_order"] == "mechanism_interleaved"]
    blocked = [row for row in all_rows if row["sequence_order"] == "recurrence_blocked"]
    return {"PRIMARY_MATCHED_CELLS.csv": primary,
            "CG1_PRIMARY_COMPARISONS.csv": comparison_rows(summary),
            "CG1_PRIMARY_CASE_COMPARISONS.csv": case_comparison_rows(summary),
            "BALANCED_INTERLEAVED_AMORTIZATION.csv": balanced,
            "BLOCKED_PREFIX_COMPOSITION_CONFOUNDED_DESCRIPTIVE.csv": blocked,
            "FIXED_I_BY_H_CONTRASTS.csv": contrast_rows(summary),
            "CHECKER_MODERATION_CONTRASTS.csv": moderation_rows(summary),
            "ACTUAL_FOUR_LIVE_CONFIRMATION_CELLS.csv": live_rows(live),
            "RESOURCE_SUMMARY_FIELDS.csv": resource_rows(resource)}


def compact_findings(summary, tables):
    comparisons = tables["CG1_PRIMARY_COMPARISONS.csv"]
    counts = {}
    for baseline in METHOD_ORDER:
        if baseline == "CG1":
            continue
        rows = [row for row in comparisons if row["baseline"] == baseline]
        counts[baseline] = {"analytic_strata": len(rows),
            "detection_gain_strata": sum(row["cg1_minus_baseline_detections"] > 0 for row in rows),
            "detection_tie_strata": sum(row["cg1_minus_baseline_detections"] == 0 for row in rows),
            "detection_loss_strata": sum(row["cg1_minus_baseline_detections"] < 0 for row in rows),
            "extra_discordant_alarm_strata": sum(row["cg1_minus_baseline_discordant_alarms"] > 0 for row in rows),
            "fewer_allocated_request_strata": sum(row["cg1_minus_baseline_allocated_requests"] < 0 for row in rows),
            "strata_are_not_independent_cases": True}
    return {"status": "PRESENTATION_OF_AUDITED_CLOSED_RESULTS",
        "primary_counterfactual_trajectories": summary["primary_counterfactual_trajectories"],
        "secondary_counterfactual_amortization_trajectories": summary["secondary_amortization_counterfactual_trajectories"],
        "physical_primary_bank_records": summary["physical_primary_native_records"],
        "independent_upstream_case_ids": summary["independently_sourced_upstream_cases"],
        "independent_upstream_case_count": len(summary["independently_sourced_upstream_cases"]),
        "actual_live_policy_cells": tables["ACTUAL_FOUR_LIVE_CONFIRMATION_CELLS.csv"],
        "factor_coverage_from_unchanged_evaluator": summary["factor_coverage"],
        "primary_comparison_stratum_counts": counts,
        "scope_notes": SCOPE_NOTES,
        "no_native_model_calls_or_reference_relabeling_by_presenter": True,
        "tosem_readiness_established": False}


def plot_results(tables, output):
    if importlib.util.find_spec("matplotlib") is None:
        return {"status": "SKIPPED_MATPLOTLIB_UNAVAILABLE", "files": []}
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "svg.fonttype": "none", "svg.hashsalt": "v9-audited-presentation-1",
                         "savefig.facecolor": "white"})
    paths = []
    def save(fig, stem):
        fig.savefig(output / (stem + ".svg"), bbox_inches="tight", metadata={"Date": None})
        fig.savefig(output / (stem + ".png"), dpi=180, bbox_inches="tight")
        plt.close(fig)
        paths.extend([stem + ".svg", stem + ".png"])
    balanced = [row for row in tables["BALANCED_INTERLEAVED_AMORTIZATION.csv"]
                if row["checker_level"] == "contract_exact" and row["impact_level"] == "observed_native_edges"
                and row["request_budget"] == 16 * row["horizon"]]
    settings = sorted({row["setting_id"] for row in balanced})
    fig, axes = plt.subplots(len(settings), 2, figsize=(9.5, 3.25 * len(settings)), squeeze=False)
    styles = {"CG1": ("#0072B2", "o"), "always_combined": ("#D55E00", "s"),
              "cost_only": ("#009E73", "^"), "budgeted_retest_all": ("#555555", "D")}
    for index, setting in enumerate(settings):
        for method, (color, marker) in styles.items():
            rows = sorted((row for row in balanced if row["setting_id"] == setting and row["method"] == method), key=lambda row: row["horizon"])
            horizons = [row["horizon"] for row in rows]
            axes[index, 0].plot(horizons, [row["mean_allocated_requests_per_world"] for row in rows], label=method, color=color, marker=marker)
            axes[index, 1].plot(horizons, [float("nan") if row["detection_fraction"] is None else row["detection_fraction"] for row in rows], color=color, marker=marker)
        axes[index, 0].set_title(setting + ": allocated request demand")
        axes[index, 1].set_title(setting + ": repeated-opportunity detection")
        axes[index, 0].set_ylabel("Mean allocated requests / recorded world")
        axes[index, 1].set_ylabel("Detected / reference opportunities")
        axes[index, 1].set_ylim(-0.03, 1.03)
        for axis in axes[index]:
            axis.set_xticks([4, 8, 16])
            axis.set_xlabel("Authored fault/repair episodes")
            axis.grid(alpha=0.25)
        axes[index, 0].legend(fontsize=7, loc="upper left")
    fig.suptitle("Balanced interleaved prefixes; exact checking, observed traces, 16 requests/episode\nSame H/A/B states recur: optimistic exact-state reuse, not unseen-version amortization", y=1.02)
    fig.tight_layout()
    save(fig, "balanced_recurrence_cost_and_detection")
    comparisons = tables["CG1_PRIMARY_COMPARISONS.csv"]
    baselines = ["cost_only", "always_combined", "budgeted_retest_all"]
    strata = sorted({tuple(row[key] for key in ("setting_id", "sequence_order", "impact_level", "checker_level", "request_budget")) for row in comparisons})
    lookup = {tuple(row[key] for key in ("setting_id", "sequence_order", "impact_level", "checker_level", "request_budget")) + (row["baseline"],): row["cg1_minus_baseline_detections"] for row in comparisons}
    data = [[lookup[stratum + (baseline,)] for baseline in baselines] for stratum in strata]
    maximum = max(1, max(abs(value) for row in data for value in row))
    fig, ax = plt.subplots(figsize=(11, max(5, len(strata) * 0.24)))
    plotted = ax.imshow(data, cmap="RdBu", norm=TwoSlopeNorm(vmin=-maximum, vcenter=0, vmax=maximum), aspect="auto")
    labels = [f"{setting} | {'blocked' if order == 'recurrence_blocked' else 'interleaved'} | {'observed' if impact == 'observed_native_edges' else 'omitted'} | {'exact' if checker == 'contract_exact' else 'noise25'} | B{budget}" for setting, order, impact, checker, budget in strata]
    ax.set_yticks(range(len(strata)), labels, fontsize=7)
    ax.set_xticks(range(len(baselines)), baselines)
    for i, row in enumerate(data):
        for j, value in enumerate(row):
            ax.text(j, i, str(value), ha="center", va="center", fontsize=7,
                    color="white" if abs(value) > maximum * 0.55 else "black")
    ax.set_title("Primary 16-episode replay: CG1 minus each baseline\nDetected repeated opportunities summed over three recorded worlds; four source cases overall")
    fig.colorbar(plotted, ax=ax, label="Detection difference within the matched analytic stratum", shrink=0.65)
    save(fig, "primary_cg1_detection_differences")
    live = tables["ACTUAL_FOUR_LIVE_CONFIRMATION_CELLS.csv"]
    fig, ax = plt.subplots(figsize=(8, 4))
    xs = list(range(len(live)))
    profiles = [row["actual_profile_native_requests"] for row in live]
    selected = [row["actual_selected_native_requests"] for row in live]
    ax.bar(xs, profiles, color="#56B4E9", label="Paid OLD profiling")
    ax.bar(xs, selected, bottom=profiles, color="#009E73", label="Fresh selected old/new queries")
    ax.axhline(28, color="#555555", linestyle="--", label="Common allowance 28")
    for x, row in zip(xs, live):
        ax.text(x, row["actual_total_native_requests"] + 0.6,
                f"{row['observed_contract_regression_pairs_IN_THIS_SELECTED_LIVE_CELL']} observed regression pairs", ha="center", fontsize=7)
    ax.set_xticks(xs, [row["setting_id"] + "\n" + row["method"] for row in live], fontsize=8)
    ax.set_ylim(0, 33)
    ax.set_ylabel("Actual native task executions")
    ax.set_title("Four actual fresh native cells: first A change, cold history, exact contracts\nCounts describe each cell; no recall denominator borrowed from another cell")
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.19), ncol=3)
    save(fig, "four_actual_native_confirmation_cells")
    return {"status": "CREATED_STATIC_SCIENTIFIC_SVG_AND_PNG", "files": paths}


def present(*, workspace, run, audit, readiness, output, summary=None, protocol=None, plots=True):
    loaded = closed_input_gate(workspace=workspace, run=run, audit=audit, readiness=readiness,
                               summary=summary, protocol=protocol)
    tables = make_tables(loaded["values"]["summary"], loaded["values"]["live"], loaded["values"]["resource"])
    findings = compact_findings(loaded["values"]["summary"], tables)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for filename, rows in tables.items():
        write_csv(output / filename, rows)
    (output / "FINDINGS.json").write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SCOPE_NOTES.txt").write_text("\n\n".join(SCOPE_NOTES) + "\n", encoding="utf-8")
    plot_record = plot_results(tables, output) if plots else {"status": "SKIPPED_BY_CALLER", "files": []}
    receipt = {"status": "COMPLETE_PRESENTATION_DERIVATIVE", "source_sha256": sha(Path(__file__)),
        "native_or_provider_calls": 0, "experimental_records_modified": False,
        "independent_audit_status": loaded["audit_status"], "independent_audit_sha256": loaded["audit_sha256"],
        "analysis_readiness_sha256": loaded["readiness_sha256"], "input_sha256": loaded["input_sha256"],
        "tables": {filename: len(rows) for filename, rows in tables.items()}, "plots": plot_record,
        "output_sha256": {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()}}
    (output / "PRESENTATION_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    result = present(workspace=args.workspace, run=args.run, audit=args.audit, readiness=args.readiness,
        output=args.output, summary=args.summary, protocol=args.protocol, plots=not args.no_plots)
    print(json.dumps({key: result[key] for key in ("status", "native_or_provider_calls", "tables", "plots")}, indent=2))


if __name__ == "__main__":
    main()

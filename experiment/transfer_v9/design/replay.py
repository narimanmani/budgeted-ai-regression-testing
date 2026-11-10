"""V9 recorded-outcome policy replay. No HTTP, model or native dispatch exists here.

All future contract truth stays in BankIndex and is looked up only for selected
responses or in the evaluator after a complete trajectory. Policy choice takes
only paid predecision cost/trace features and earlier own operational verdicts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import time

GUIDANCE_SHA256 = "f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989"
METHODS = ("seeded_random", "cost_only", "impact_only", "history_only",
           "always_combined", "CG1", "budgeted_retest_all")
PROFILE_METHODS = {"cost_only", "impact_only", "history_only", "always_combined", "CG1"}
IMPACT_METHODS = {"impact_only", "always_combined", "CG1"}
FIXED_ARMS = {"cost_only": "I0_H0", "impact_only": "I1_H0",
              "history_only": "I0_H1", "always_combined": "I1_H1"}


class ReplayProtocolError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode("utf-8")).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_guidance(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[3] / "experiment/validation_v7/guidance/policy.py"
    if file_digest(path) != GUIDANCE_SHA256:
        raise ReplayProtocolError("CG1 source differs from original frozen bytes")
    spec = importlib.util.spec_from_file_location("v9_original_cg1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _number(value, positive=False):
    return (type(value) in (float, int) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def hash_fraction(seed, kind, *identities):
    return int(digest([seed, kind, *identities])[:16], 16) / float(2 ** 64)


def sequence_episodes(order, horizon=16):
    if type(horizon) is not int or horizon < 4 or horizon % 4:
        raise ReplayProtocolError("Registered sequence horizon must be a positive multiple of four")
    full_cases = (["A"] * 4 + ["B"] * 4 if order == "recurrence_blocked"
                  else ["A", "B"] * 4 if order == "mechanism_interleaved" else None)
    if full_cases is None or horizon > 16:
        raise ReplayProtocolError("Unknown sequence or unregistered horizon")
    episodes = []
    for case in full_cases:
        episodes += [{"case_key": case, "old_state": "H", "new_state": case, "direction": "fault"},
                     {"case_key": case, "old_state": case, "new_state": "H", "direction": "repair"}]
    return [{**episode, "episode_index": i + 1} for i, episode in enumerate(episodes[:horizon])]


class BankIndex:
    """Evaluator/source store, never passed to the chooser or fixed rankers."""
    def __init__(self, bank, guidance):
        if bank.get("schema_version") != "v9-native-bank-1":
            raise ReplayProtocolError("Unknown normalized native bank schema")
        self.settings = {}
        for setting in bank.get("settings", []):
            sid = setting.get("setting_id")
            tasks = setting.get("task_ids", [])
            if not sid or sid in self.settings or len(tasks) != 8 or len(set(tasks)) != 8:
                raise ReplayProtocolError("Each setting needs a distinct identity and complete eight-task catalog")
            if set(setting.get("states", {})) != {"H", "A", "B"} or set(setting.get("case_ids", {})) != {"A", "B"}:
                raise ReplayProtocolError("Setting must pin H/A/B and the two historical cases")
            if not _number(setting.get("common_setup_seconds", 0.0)):
                raise ReplayProtocolError("Common setup seconds must be a finite nonnegative exclusive allocation")
            for state in setting["states"].values():
                if not _sha(state.get("state_digest")):
                    raise ReplayProtocolError("Exact code/input/config state digest is required")
                guidance.tokens(state.get("changed_tokens", []))
            if len({x["state_digest"] for x in setting["states"].values()}) != 3:
                raise ReplayProtocolError("The three distinct native states need distinct byte-closure digests")
            for case_key in ("A", "B"):
                if not setting["states"][case_key]["changed_tokens"]:
                    raise ReplayProtocolError("A historical change needs public production-path tokens")
            self.settings[sid] = setting
        self.records, self.ids = {}, set()
        self.raw_count = len(bank.get("records", []))
        for record in bank.get("records", []):
            sid = record.get("setting_id")
            if sid not in self.settings:
                raise ReplayProtocolError("Record setting is not registered")
            setting = self.settings[sid]
            if record.get("task_id") not in setting["task_ids"]:
                raise ReplayProtocolError("Record task is not in the complete catalog")
            case_key = next((key for key, value in setting["case_ids"].items() if value == record.get("case_id")), None)
            if case_key is None or record.get("state") not in ("H", case_key):
                raise ReplayProtocolError("Record case/state pairing is not registered")
            if type(record.get("pass_index")) is not int or record["pass_index"] not in (0, 1, 2):
                raise ReplayProtocolError("Primary replay bank must contain exactly passes 0/1/2")
            if type(record.get("contract_pass")) is not bool:
                raise ReplayProtocolError("Native reference contract outcome must be a boolean")
            if not _number(record.get("elapsed_seconds"), True) or not all(
                    _number(record.get(key)) for key in ("checker_seconds", "feature_seconds")):
                raise ReplayProtocolError("Native/checker/feature durations must be finite, exclusive components")
            if not all(_sha(record.get(key)) for key in ("raw_sha256", "receipt_sha256")):
                raise ReplayProtocolError("Native records require bound raw and operation receipts")
            guidance.tokens(record.get("observed_dependency_tokens", []))
            rid = record.get("record_id")
            key = (sid, record["case_id"], record["state"], record["task_id"], record["pass_index"])
            if not rid or rid in self.ids or key in self.records:
                raise ReplayProtocolError("Duplicate native record identity or factorial cell")
            self.ids.add(rid)
            self.records[key] = record
        expected = sum(2 * 2 * len(s["task_ids"]) * 3 for s in self.settings.values())
        if len(self.records) != expected:
            raise ReplayProtocolError(f"Native bank has {len(self.records)} records; complete frame needs {expected}")
        for sid, setting in self.settings.items():
            for case_key, case_id in setting["case_ids"].items():
                for state, task, p in itertools.product(("H", case_key), setting["task_ids"], range(3)):
                    if (sid, case_id, state, task, p) not in self.records:
                        raise ReplayProtocolError("Native bank omits a registered task/state/pass")

    def record(self, sid, case_id, state, task, native_pass):
        return self.records[(sid, case_id, state, task, native_pass)]

    def profile_observations(self, sid, state):
        """Only old durations/observed paths/receipt IDs cross the feature boundary."""
        setting = self.settings[sid]
        case_id = setting["case_ids"]["A" if state == "H" else state]
        result = {}
        for task in setting["task_ids"]:
            rows = [self.record(sid, case_id, state, task, p) for p in range(3)]
            result[task] = [{key: row[key] for key in (
                "record_id", "elapsed_seconds", "feature_seconds", "observed_dependency_tokens", "receipt_sha256")}
                for row in rows]
        return result


def _impact_block(guidance, setting, old_state, public_profile, changed_tokens,
                  level, seed, feature_block_id, episode_index):
    admitted, edge_count, retained = [], 0, 0
    task_ids = setting["task_ids"]
    for task in task_ids:
        edges = set()
        for sample in public_profile[task]:
            edges.update(sample["observed_dependency_tokens"])
        edge_count += len(edges)
        if level == "seeded_edge_omission":
            edges = {edge for edge in edges if hash_fraction(
                seed, "edge_omission", setting["setting_id"], setting["states"][old_state]["state_digest"], task, edge) >= 0.25}
        elif level != "observed_native_edges":
            raise ReplayProtocolError("Unregistered impact level")
        retained += len(edges)
        if set(changed_tokens).intersection(edges):
            admitted.append(task)
    evidence = {"source": "paid_old_native_contexts", "feature_block_id": feature_block_id,
                "episode_index": episode_index, "predecision": True,
                "current_or_future_outcomes_used": False, "provenance_verified": True,
                "task_ids": list(task_ids), "admitted_task_ids": admitted,
                "changed_tokens": list(changed_tokens),
                "evidence_receipt_sha256": digest({"public_profile": public_profile, "level": level, "seed": seed})}
    # Let the original guide implement empty/nonselective/provenance fallbacks.
    effective, reason = guidance.checked_impact(evidence, task_ids, changed_tokens, feature_block_id, episode_index)
    return evidence, effective, {"observed_edges": edge_count, "retained_edges": retained,
                                 "omitted_edges": edge_count - retained, "admission_reason": reason}


def select_policy(guidance, *, method, task_ids, pair_costs, impact, history,
                  trajectory_id, feature_block_id, episode_index, changed_tokens,
                  pair_limit, seed, setting_id, sequence_order, native_pass):
    """Pure policy boundary: no BankIndex, reference labels, or new outputs."""
    if pair_limit < 1:
        return {"chosen_arm": None, "nominal_ordered_task_ids": [], "nominal_prefix_task_ids": [],
                "reasons": ["no_affordable_pair_after_required_acquisition"],
                "uses_reference_or_current_new_outcomes": False}
    if method == "CG1":
        return guidance.choose(task_ids, pair_costs, impact, history,
            trajectory_id=trajectory_id, feature_block_id=feature_block_id,
            episode_index=episode_index, changed_tokens=changed_tokens, pair_limit=pair_limit)
    if method not in METHODS:
        raise ReplayProtocolError("Unregistered policy")
    if method == "budgeted_retest_all":
        order, arm, reason = list(task_ids), None, "registered_catalog_order_under_common_budget_allocator"
    elif method == "seeded_random":
        order = sorted(task_ids, key=lambda task: digest([
            seed, "random_order", setting_id, sequence_order, native_pass, episode_index, task]))
        arm, reason = None, "precommitted_seeded_random_order"
    else:
        positive = guidance.checked_history(history, task_ids, trajectory_id, episode_index)
        counts = Counter(event["task_id"] for event in positive)
        admitted, reason = guidance.checked_impact(impact, task_ids, changed_tokens, feature_block_id, episode_index)
        arm = FIXED_ARMS[method]
        order = guidance.rank_arm(task_ids, pair_costs, admitted, counts, arm)
    return {"chosen_arm": arm, "nominal_ordered_task_ids": order,
            "nominal_prefix_task_ids": order[:pair_limit], "reasons": [reason],
            "uses_reference_or_current_new_outcomes": False}


def _operational_verdict(record, level, seed, setting_id, order, native_pass,
                         episode_index, task, endpoint, probability):
    # The mask identity never contains truth, arm, impact level, or budget.
    # Paired counterfactual arms therefore see the same potential endpoint noise.
    if level not in ("contract_exact", "seeded_symmetric_flip_p25"):
        raise ReplayProtocolError("Unknown operational checker intervention")
    started = time.process_time_ns()
    flip = (False if level == "contract_exact" else hash_fraction(
        seed, "operational_flip", setting_id, order, native_pass, episode_index, task, endpoint) < probability)
    outcome = record["contract_pass"] != flip
    return outcome, flip, (time.process_time_ns() - started) / 1_000_000_000


def run_trajectory(bank, protocol, guidance, *, setting_id, sequence_order,
                   native_pass, impact_level, checker_level, request_budget,
                   method, horizon=16, analysis_frame="primary"):
    setting = bank.settings[setting_id]
    task_ids = setting["task_ids"]
    seed = protocol["replay"]["seed"]
    probability = protocol["replay"]["operational_error_probability"]
    identity = {"setting_id": setting_id, "sequence_order": sequence_order,
                "native_pass": native_pass, "impact_level": impact_level,
                "checker_level": checker_level, "request_budget": request_budget,
                "method": method, "horizon": horizon, "analysis_frame": analysis_frame}
    trajectory_id = digest(identity)
    history, profiles, rows = [], {}, []
    costs = {"profile_requests": 0, "selected_requests": 0,
             "profile_native_seconds": 0.0, "selected_native_seconds": 0.0,
             "feature_seconds": 0.0, "checker_seconds": 0.0,
             "decision_cpu_seconds": 0.0, "operational_mask_cpu_seconds": 0.0,
             "common_setup_seconds": setting.get("common_setup_seconds", 0.0)}
    episodes = sequence_episodes(sequence_order, horizon)
    for offset, episode in enumerate(episodes):
        decision_cpu_started = time.process_time_ns()
        idx, old_state, new_state = episode["episode_index"], episode["old_state"], episode["new_state"]
        case_key = episode["case_key"]
        remaining = request_budget - costs["profile_requests"] - costs["selected_requests"]
        changed = guidance.tokens(setting["states"][case_key]["changed_tokens"])
        state_digest = setting["states"][old_state]["state_digest"]
        profile_key = digest([state_digest, task_ids])
        acquisition = None
        acquisition_denied = False
        if method in PROFILE_METHODS and profile_key not in profiles:
            needed = 3 * len(task_ids)
            if remaining < needed:
                acquisition_denied = True
            else:
                public = bank.profile_observations(setting_id, old_state)
                pair_costs = guidance.paired_cost_profile({
                    task: [x["elapsed_seconds"] for x in samples] for task, samples in public.items()})
                profiles[profile_key] = {"public": public, "pair_costs": pair_costs}
                costs["profile_requests"] += needed
                native_seconds = sum(x["elapsed_seconds"] for samples in public.values() for x in samples)
                feature_seconds = (sum(x["feature_seconds"] for samples in public.values() for x in samples)
                                   if method in IMPACT_METHODS else 0.0)
                costs["profile_native_seconds"] += native_seconds
                costs["feature_seconds"] += feature_seconds
                acquisition = {"profile_key": profile_key, "old_state": old_state, "requests": needed,
                               "native_seconds": native_seconds, "feature_seconds": feature_seconds,
                               "record_ids": [x["record_id"] for samples in public.values() for x in samples]}
                remaining -= needed
        pair_limit = min(len(task_ids), remaining // (2 * (horizon - offset)))
        if acquisition_denied:
            pair_limit = 0
        feature_id = digest([trajectory_id, idx, profile_key])
        pair_costs, impact, impact_stats = {}, None, {"observed_edges": 0, "retained_edges": 0, "omitted_edges": 0}
        if method in PROFILE_METHODS and not acquisition_denied:
            pair_costs = profiles[profile_key]["pair_costs"]
            if method in IMPACT_METHODS:
                impact, _, impact_stats = _impact_block(guidance, setting, old_state,
                    profiles[profile_key]["public"], changed, impact_level, seed, feature_id, idx)
        positive = guidance.checked_history(history, task_ids, trajectory_id, idx)
        decision_inputs = {"method": method, "task_ids": task_ids, "pair_costs": pair_costs,
                           "impact": impact, "history": history, "trajectory_id": trajectory_id,
                           "feature_block_id": feature_id, "episode_index": idx,
                           "changed_tokens": changed, "pair_limit": pair_limit, "seed": seed,
                           "setting_id": setting_id, "sequence_order": sequence_order, "native_pass": native_pass}
        # Selection and its sealed inputs are constructed before selected lookup.
        decision = select_policy(guidance, **decision_inputs)
        predecision = {"input_sha256": digest(decision_inputs), "feature_block_id": feature_id,
                       "pair_limit": pair_limit, "remaining_requests_after_acquisition": remaining,
                       "history_event_count": len(history), "positive_history_count": len(positive),
                       "pair_costs": pair_costs, "impact": impact, "public_changed_tokens": changed,
                       "decision": decision, "uses_current_or_future_reference": False}
        costs["decision_cpu_seconds"] += (time.process_time_ns() - decision_cpu_started) / 1_000_000_000
        selected = list(decision["nominal_prefix_task_ids"])
        pair_rows = []
        for task in selected:
            if request_budget - costs["profile_requests"] - costs["selected_requests"] < 2:
                raise ReplayProtocolError("Selector/scheduler exceeded the hard request budget")
            case_id = setting["case_ids"][case_key]
            old = bank.record(setting_id, case_id, old_state, task, native_pass)
            new = bank.record(setting_id, case_id, new_state, task, native_pass)
            old_op, old_flip, old_cpu = _operational_verdict(old, checker_level, seed,
                setting_id, sequence_order, native_pass, idx, task, "old", probability)
            new_op, new_flip, new_cpu = _operational_verdict(new, checker_level, seed,
                setting_id, sequence_order, native_pass, idx, task, "new", probability)
            costs["selected_requests"] += 2
            costs["selected_native_seconds"] += old["elapsed_seconds"] + new["elapsed_seconds"]
            costs["checker_seconds"] += old["checker_seconds"] + new["checker_seconds"]
            costs["operational_mask_cpu_seconds"] += old_cpu + new_cpu
            feedback_cpu_started = time.process_time_ns()
            receipt = {"source": "counterfactual_selected_native_record_pair",
                       "trajectory_id": trajectory_id, "episode_index": idx, "task_id": task,
                       "old_record_id": old["record_id"], "new_record_id": new["record_id"],
                       "old_native_receipt_sha256": old["receipt_sha256"],
                       "new_native_receipt_sha256": new["receipt_sha256"],
                       "old_operational_pass": old_op, "new_operational_pass": new_op,
                       "old_mask_flipped": old_flip, "new_mask_flipped": new_flip}
            receipt_sha = digest(receipt)
            event = {"source": "own_observed_paired_execution", "trajectory_id": trajectory_id,
                     "task_id": task, "episode_index": idx, "selected": True, "timely": True,
                     "old_primary_pass": old_op, "new_primary_pass": new_op,
                     "changed_tokens": changed, "receipt_sha256": receipt_sha}
            history.append(event)
            pair_rows.append({"receipt": receipt, "receipt_sha256": receipt_sha, "history_event": event})
            costs["decision_cpu_seconds"] += (time.process_time_ns() - feedback_cpu_started) / 1_000_000_000
        used = costs["profile_requests"] + costs["selected_requests"]
        if used > request_budget:
            raise ReplayProtocolError("Hard budget was exceeded")
        rows.append({**episode, "case_id": setting["case_ids"][case_key], "acquisition": acquisition,
                     "acquisition_denied": acquisition_denied, "predecision": predecision,
                     "impact_stats": impact_stats, "selected_pairs": pair_rows,
                     "cumulative_costs": dict(costs), "remaining_request_units": request_budget - used})
    # Evaluation starts only after all selections and operational histories close.
    result = {"trajectory_id": trajectory_id, "identity": identity, "episodes": rows,
              "final_costs": costs, "no_live_native_dispatch": True}
    result["final_costs"]["total_allocated_wall_seconds"] = sum(costs[key] for key in (
        "profile_native_seconds", "selected_native_seconds", "feature_seconds", "checker_seconds", "common_setup_seconds"))
    result["final_costs"]["total_allocated_native_wall_plus_controller_cpu_proxy_seconds"] = (
        result["final_costs"]["total_allocated_wall_seconds"] + costs["decision_cpu_seconds"]
        + costs["operational_mask_cpu_seconds"])
    result["metrics"] = evaluate_trajectory(bank, result)
    return result


def evaluate_trajectory(bank, trajectory):
    identity = trajectory["identity"]
    sid, native_pass = identity["setting_id"], identity["native_pass"]
    setting = bank.settings[sid]
    totals = Counter()
    cases, episode_metrics = defaultdict(Counter), []
    for row in trajectory["episodes"]:
        metrics = Counter()
        case_id, old_state, new_state = row["case_id"], row["old_state"], row["new_state"]
        references = {}
        for task in setting["task_ids"]:
            old = bank.record(sid, case_id, old_state, task, native_pass)["contract_pass"]
            new = bank.record(sid, case_id, new_state, task, native_pass)["contract_pass"]
            references[task] = (old, new)
            metrics["reference_regression_opportunities"] += int(old and not new)
            metrics["reference_repairs"] += int(not old and new)
        for pair in row["selected_pairs"]:
            receipt = pair["receipt"]
            old, new = references[receipt["task_id"]]
            regression = old and not new
            alarm = receipt["old_operational_pass"] and not receipt["new_operational_pass"]
            metrics["selected_pairs"] += 1
            metrics["selected_true_regressions"] += int(regression)
            metrics["detected_true_regressions"] += int(regression and alarm)
            metrics["reference_discordant_alarms"] += int(alarm and not regression)
            metrics["repair_alarms"] += int(alarm and not old and new)
            metrics["endpoint_judgments"] += 2
            metrics["controlled_endpoint_flips"] += int(receipt["old_mask_flipped"]) + int(receipt["new_mask_flipped"])
            for truth, operational in ((old, receipt["old_operational_pass"]), (new, receipt["new_operational_pass"])):
                metrics["reference_passing_endpoints"] += int(truth)
                metrics["reference_failing_endpoints"] += int(not truth)
                metrics["operational_false_failures"] += int(truth and not operational)
                metrics["operational_false_passes"] += int(not truth and operational)
        metrics["missed_reference_regressions"] = (metrics["reference_regression_opportunities"]
                                                  - metrics["detected_true_regressions"])
        totals.update(metrics)
        cases[case_id].update(metrics)
        episode_metrics.append({"episode_index": row["episode_index"], "case_id": case_id, **metrics})
    return {"totals": dict(totals), "by_upstream_case": {key: dict(value) for key, value in cases.items()},
            "per_episode": episode_metrics,
            "opportunities_are_repeated_task_change_instances_not_independent_defects": True}


def _cell_key(identity, include_method=True):
    keys = ("analysis_frame", "horizon", "setting_id", "sequence_order", "impact_level", "checker_level", "request_budget")
    return tuple(identity[key] for key in keys) + ((identity["method"],) if include_method else ())


def summarize(trajectories, bank, protocol):
    groups, comparisons = {}, []
    for tr in trajectories:
        key = _cell_key(tr["identity"])
        group = groups.setdefault(key, {"identity": {k: v for k, v in tr["identity"].items() if k != "native_pass"},
                                       "native_passes": [], "totals": Counter(), "costs": Counter(),
                                       "by_upstream_case": defaultdict(Counter)})
        group["native_passes"].append(tr["identity"]["native_pass"])
        group["totals"].update(tr["metrics"]["totals"])
        group["costs"].update(tr["final_costs"])
        for case_id, metrics in tr["metrics"]["by_upstream_case"].items():
            group["by_upstream_case"][case_id].update(metrics)
    cells = list(groups.values())
    by_matched = defaultdict(dict)
    for group in cells:
        by_matched[_cell_key(group["identity"], False)][group["identity"]["method"]] = group
    for methods in by_matched.values():
        cg = methods["CG1"]
        for method, baseline in methods.items():
            if method == "CG1":
                continue
            comparisons.append({"identity": {k: v for k, v in cg["identity"].items() if k != "method"},
                "baseline": method,
                "cg1_minus_baseline_detections": cg["totals"]["detected_true_regressions"] - baseline["totals"]["detected_true_regressions"],
                "cg1_minus_baseline_discordant_alarms": cg["totals"]["reference_discordant_alarms"] - baseline["totals"]["reference_discordant_alarms"],
                "cg1_minus_baseline_allocated_requests": sum(cg["costs"][k] - baseline["costs"][k] for k in ("profile_requests", "selected_requests")),
                "by_upstream_case": {case_id: {
                    "detection_delta": cg["by_upstream_case"][case_id]["detected_true_regressions"]
                        - baseline["by_upstream_case"][case_id]["detected_true_regressions"],
                    "discordant_alarm_delta": cg["by_upstream_case"][case_id]["reference_discordant_alarms"]
                        - baseline["by_upstream_case"][case_id]["reference_discordant_alarms"]}
                    for case_id in sorted(cg["by_upstream_case"])}})
    distinct_admission = 0
    grouped_episodes = defaultdict(dict)
    for tr in trajectories:
        for row in tr["episodes"]:
            identity = tr["identity"]
            if identity["method"] not in IMPACT_METHODS:
                continue
            key = tuple(identity[k] for k in ("analysis_frame", "horizon", "setting_id", "sequence_order",
                                            "native_pass", "checker_level", "request_budget", "method")) + (row["episode_index"],)
            block = row["predecision"]["impact"]
            grouped_episodes[key][identity["impact_level"]] = None if block is None else block["admitted_task_ids"]
    for levels in grouped_episodes.values():
        if len(levels) == 2 and len({json.dumps(value) for value in levels.values()}) > 1:
            distinct_admission += 1
    cg_rows = [row for tr in trajectories if tr["identity"]["method"] == "CG1" for row in tr["episodes"]]
    selective_by_level = {level: sum(
        0 < len(row["predecision"]["impact"]["admitted_task_ids"]) < 8
        for tr in trajectories if tr["identity"]["method"] == "CG1" and tr["identity"]["impact_level"] == level
        for row in tr["episodes"] if row["predecision"]["impact"] is not None)
        for level in protocol["replay"]["impact_levels"]}
    positive_history = sum(row["predecision"]["positive_history_count"] > 0 for row in cg_rows)
    contrasts, moderation = fixed_arm_contrasts(by_matched)
    return {
        "status": "COMPLETE_RECORDED_OUTCOME_REPLAY",
        "guidance_source_sha256": GUIDANCE_SHA256,
        "physical_primary_native_records": bank.raw_count,
        "settings": sorted(bank.settings), "independently_sourced_upstream_cases": sorted({
            case for setting in bank.settings.values() for case in setting["case_ids"].values()}),
        "primary_counterfactual_trajectories": sum(tr["identity"]["analysis_frame"] == "primary" for tr in trajectories),
        "secondary_amortization_counterfactual_trajectories": sum(tr["identity"]["analysis_frame"] != "primary" for tr in trajectories),
        "all_counterfactual_decisions": sum(len(tr["episodes"]) for tr in trajectories),
        "factor_coverage": {"cg1_selective_admission_decisions_by_level": selective_by_level,
                            "paired_decisions_with_omission_changed_admission": distinct_admission,
                            "cg1_decisions_with_own_positive_history": positive_history,
                            "cg1_executed_decisions_choosing_impact": sum(
                                row["predecision"]["decision"].get("chosen_arm") in ("I1_H0", "I1_H1")
                                and bool(row["selected_pairs"]) for row in cg_rows),
                            "cg1_executed_decisions_choosing_history": sum(
                                row["predecision"]["decision"].get("chosen_arm") in ("I0_H1", "I1_H1")
                                and bool(row["selected_pairs"]) for row in cg_rows),
                            "controlled_endpoint_flips_across_replayed_allocations": sum(
                                tr["metrics"]["totals"].get("controlled_endpoint_flips", 0) for tr in trajectories)},
        "matched_cells": cells, "cg1_comparisons": comparisons,
        "fixed_arm_impact_by_history_contrasts": contrasts,
        "checker_moderation_of_fixed_arm_impact_by_history": moderation,
        "new_native_or_model_dispatches_in_replay": 0,
        "replayed_allocations_must_not_be_summed_as_physical_requests": True,
        "replay_controller_cpu_is_measured_separately_from_native_query_time": True,
        "controller_wall_time_is_measured": False,
        "native_wall_plus_controller_cpu_is_a_hybrid_proxy_not_complete_wall_time": True,
        "reanalysis_machine_time_fields_are_not_expected_byte_identical": [
            "decision_cpu_seconds", "operational_mask_cpu_seconds",
            "total_allocated_native_wall_plus_controller_cpu_proxy_seconds"],
        "amortization_composition_notice": "Interleaved 4/8/16 prefixes balance both cases; blocked 4/8 prefixes contain A only, while blocked16 contains A+B. Blocked-prefix changes confound horizon with case composition and remain descriptive.",
        "complete_application_level_external_validation_established": False,
        "portable_guidance_or_tosem_readiness_established": False,
        "interpretation": "Finite recorded-outcome contrasts; authored sequence/omission/checker interventions; repeated tasks are not independent defects.",
    }


def fixed_arm_contrasts(by_matched):
    """Descriptive difference-in-differences of four registered fixed regimes."""
    contrasts, moderation, moderation_groups = [], [], defaultdict(dict)
    for methods in by_matched.values():
        identity = {k: v for k, v in methods["cost_only"]["identity"].items() if k != "method"}
        values = {}
        for metric in ("detected_true_regressions", "reference_discordant_alarms", "allocated_requests"):
            def value(method):
                return (sum(methods[method]["costs"][k] for k in ("profile_requests", "selected_requests"))
                        if metric == "allocated_requests" else methods[method]["totals"][metric])
            values[metric] = value("always_combined") - value("impact_only") - value("history_only") + value("cost_only")
        row = {"identity": identity, "combined_minus_impact_minus_history_plus_cost": values,
               "interpretation": "Finite recorded-outcome sequential policy-regime contrast; case histories can differ by prior selections."}
        contrasts.append(row)
        key = tuple((k, v) for k, v in sorted(identity.items()) if k != "checker_level")
        moderation_groups[key][identity["checker_level"]] = row
    for key, levels in moderation_groups.items():
        if set(levels) != {"contract_exact", "seeded_symmetric_flip_p25"}:
            raise ReplayProtocolError("Checker moderation requires both registered operational-checker levels")
        accurate = levels["contract_exact"]["combined_minus_impact_minus_history_plus_cost"]
        noisy = levels["seeded_symmetric_flip_p25"]["combined_minus_impact_minus_history_plus_cost"]
        moderation.append({"identity": dict(key), "noisy_minus_exact_I_by_H_contrast": {
            metric: noisy[metric] - accurate[metric] for metric in accurate},
            "population_oracle_accuracy_estimated": False})
    return contrasts, moderation


def run_factorial(bank_data, protocol, guidance=None):
    guidance = guidance or load_guidance()
    bank = BankIndex(bank_data, guidance)
    replay = protocol["replay"]
    if len(bank.settings) != protocol["native_bank"]["settings"]:
        raise ReplayProtocolError("Native setting count differs from frozen protocol")
    if set(replay["methods"]) != set(METHODS) or len(replay["methods"]) != len(METHODS):
        raise ReplayProtocolError("The seven-arm comparison must remain complete")
    if replay["operational_error_probability"] != 0.25 or replay["impact_omission_probability"] != 0.25:
        raise ReplayProtocolError("This execution implementation pins both controlled perturbation rates at 0.25")
    trajectories = []
    horizons = protocol["analysis"].get("predeclared_secondary_amortization_horizons", [16])
    per_episode = protocol["analysis"].get("amortization_request_allowance_per_episode", [8, 16])
    if horizons != [4, 8, 16] or per_episode != [8, 16]:
        raise ReplayProtocolError("Only the registered 4/8/16-horizon and 8/16-per-episode amortization frame is supported")
    if (replay["sequences"] != ["recurrence_blocked", "mechanism_interleaved"]
            or replay["impact_levels"] != ["observed_native_edges", "seeded_edge_omission"]
            or replay["operational_checker_levels"] != ["contract_exact", "seeded_symmetric_flip_p25"]
            or replay["recorded_outcome_passes"] != 3):
        raise ReplayProtocolError("The complete registered sequence/impact/checker/native-pass frame is required")
    for key in ("current_or_future_truth_to_selector", "reference_outcomes_to_selector",
                "selection_uses_true_failure_labels", "operational_error_mask_depends_on_truth",
                "impact_omission_depends_on_current_fault_outcomes"):
        if replay.get(key) is not False:
            raise ReplayProtocolError("Forbidden prospective truth leakage declaration: " + key)
    if replay["episodes_per_sequence"] != 16 or replay["end_to_end_budget_native_request_units"] != [128, 256]:
        raise ReplayProtocolError("The primary frame is sixteen episodes under 128/256 request units")
    for horizon in horizons:
        budgets = [horizon * allowance for allowance in per_episode]
        if horizon == 16:
            frame = "primary"
        else:
            frame = "secondary_amortization"
        for sid, order, p, impact, checker, budget, method in itertools.product(
                sorted(bank.settings), replay["sequences"], range(replay["recorded_outcome_passes"]),
                replay["impact_levels"], replay["operational_checker_levels"], budgets, replay["methods"]):
            trajectories.append(run_trajectory(bank, protocol, guidance,
                setting_id=sid, sequence_order=order, native_pass=p, impact_level=impact,
                checker_level=checker, request_budget=budget, method=method, horizon=horizon, analysis_frame=frame))
    return {"summary": summarize(trajectories, bank, protocol), "trajectories": trajectories}


def compare_confirmation(primary_bank, confirmation_bank, guidance=None):
    """Fresh same-case observations are a stability diagnostic, never replacement gold."""
    index = BankIndex(primary_bank, guidance or load_guidance())
    fresh_rows = confirmation_bank.get("records", [])
    fresh_ids = [row.get("record_id") for row in fresh_rows]
    fresh_receipts = [row.get("receipt_sha256") for row in fresh_rows]
    if (not all(isinstance(value, str) and value for value in fresh_ids)
            or len(fresh_ids) != len(set(fresh_ids))):
        raise ReplayProtocolError("Duplicate or missing fresh confirmation record identity")
    if (not all(_sha(value) for value in fresh_receipts)
            or len(fresh_receipts) != len(set(fresh_receipts))):
        raise ReplayProtocolError("Duplicate or malformed actual fresh confirmation operation receipt")
    static_fields = ("setting_id", "task_ids", "case_ids", "states")
    original_settings = {sid: {key: row[key] for key in static_fields} for sid, row in index.settings.items()}
    fresh_settings = {row["setting_id"]: {key: row[key] for key in static_fields}
                      for row in confirmation_bank.get("settings", [])}
    if fresh_settings != original_settings:
        raise ReplayProtocolError("Confirmation task catalogs, case identities or pinned states differ from the primary bank")
    original_receipts = {row["receipt_sha256"] for row in index.records.values()}
    observed = {}
    for row in fresh_rows:
        key = (row["setting_id"], row["case_id"], row["state"], row["task_id"])
        if key in observed or row.get("pass_index") != 3 or type(row.get("contract_pass")) is not bool:
            raise ReplayProtocolError("Confirmation requires one fresh pass3 observation per original native cell")
        if (not row.get("record_id") or row["record_id"] in index.ids
                or not all(_sha(row.get(field)) for field in ("raw_sha256", "receipt_sha256"))
                or row["receipt_sha256"] in original_receipts):
            raise ReplayProtocolError("Confirmation must bind a distinct native operation, not reuse a primary receipt")
        observed[key] = row
    expected = {(sid, case_id, state, task) for sid, case_id, state, task, _ in index.records}
    if set(observed) != expected:
        raise ReplayProtocolError("Fresh confirmation does not cover exactly the complete registered native frame")
    rows = []
    for key in sorted(expected):
        primary = [index.records[(*key, p)] for p in range(3)]
        fresh = observed[key]
        outcomes = [record["contract_pass"] for record in primary]
        rows.append({"setting_id": key[0], "case_id": key[1], "state": key[2], "task_id": key[3],
                     "primary_outcomes": outcomes, "confirmation_outcome": fresh["contract_pass"],
                     "primary_is_stable": len(set(outcomes)) == 1,
                     "confirmation_agrees_with_all_primary": all(value == fresh["contract_pass"] for value in outcomes),
                     "primary_record_ids": [record["record_id"] for record in primary],
                     "confirmation_record_id": fresh["record_id"]})
    return {"status": "COMPLETE_SAME_CASE_NATIVE_STABILITY_DIAGNOSTIC",
            "primary_native_records": len(index.records), "fresh_confirmation_records": len(observed),
            "stable_primary_cells": sum(row["primary_is_stable"] for row in rows),
            "confirmation_cells_agreeing_with_all_primary": sum(row["confirmation_agrees_with_all_primary"] for row in rows),
            "disagreements_retained": [row for row in rows if not row["confirmation_agrees_with_all_primary"]],
            "cells": rows, "primary_or_reference_labels_replaced": False,
            "new_independent_case_or_application_samples": 0}


def write_outputs(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "trajectories").mkdir()
    for trajectory in result["trajectories"]:
        (output / "trajectories" / (trajectory["trajectory_id"] + ".json")).write_text(
            json.dumps(trajectory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SUMMARY.json").write_text(json.dumps(result["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = []
    for cell in result["summary"]["matched_cells"]:
        rows.append({**cell["identity"], **cell["totals"], **cell["costs"]})
    keys = sorted({key for row in rows for key in row})
    with (output / "MATCHED_CELLS.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    (output / "CG1_COMPARISONS.json").write_text(json.dumps(result["summary"]["cg1_comparisons"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if "confirmation" in result:
        (output / "SAME_CASE_CONFIRMATION.json").write_text(json.dumps(result["confirmation"], indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--guidance", type=Path)
    parser.add_argument("--confirmation", type=Path)
    args = parser.parse_args()
    bank = json.loads(args.bank.read_text(encoding="utf-8-sig"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8-sig"))
    result = run_factorial(bank, protocol, load_guidance(args.guidance))
    result["summary"]["bank_sha256"] = file_digest(args.bank)
    result["summary"]["protocol_sha256"] = file_digest(args.protocol)
    if args.confirmation:
        confirmation = json.loads(args.confirmation.read_text(encoding="utf-8-sig"))
        result["confirmation"] = compare_confirmation(bank, confirmation, load_guidance(args.guidance))
        result["summary"]["confirmation_bank_sha256"] = file_digest(args.confirmation)
        result["summary"]["same_case_confirmation_record"] = "SAME_CASE_CONFIRMATION.json"
    write_outputs(result, args.output)
    print(json.dumps({key: result["summary"][key] for key in (
        "status", "physical_primary_native_records", "primary_counterfactual_trajectories",
        "secondary_amortization_counterfactual_trajectories", "all_counterfactual_decisions",
        "new_native_or_model_dispatches_in_replay")}, indent=2))


if __name__ == "__main__":
    main()

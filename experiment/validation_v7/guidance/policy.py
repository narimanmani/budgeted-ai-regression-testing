"""CG1: a new, unvalidated conditional chooser for four fixed testing arms.

Pure decision code: no files, reference bank, native application or model calls.
Only public predecision change tokens, paid old-state features and the current
trajectory's earlier selected paired judgments are accepted.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter

VERSION = 'CG1-2026-11-01'
ARMS = {'I0_H0': (False, False), 'I1_H0': (True, False),
        'I0_H1': (False, True), 'I1_H1': (True, True)}
SIMPLICITY_ORDER = ('I0_H0', 'I1_H0', 'I0_H1', 'I1_H1')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
TOKEN_PREFIXES = {'code', 'config', 'dependency', 'document'}
HISTORY_FIELDS = {'source', 'trajectory_id', 'task_id', 'episode_index', 'selected',
                  'timely', 'old_primary_pass', 'new_primary_pass', 'changed_tokens', 'receipt_sha256'}
IMPACT_FIELDS = {'source', 'feature_block_id', 'episode_index', 'predecision',
                 'current_or_future_outcomes_used', 'provenance_verified', 'task_ids',
                 'admitted_task_ids', 'changed_tokens', 'evidence_receipt_sha256'}


class GuidanceProtocolError(ValueError):
    pass


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def is_sha(value):
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def tokens(values):
    if not isinstance(values, (list, tuple)):
        raise GuidanceProtocolError('Public change tokens must be a list/tuple')
    result = set()
    for value in values:
        if not isinstance(value, str) or ':' not in value:
            raise GuidanceProtocolError('Change token requires a declared public namespace')
        prefix, body = value.split(':', 1)
        if (prefix not in TOKEN_PREFIXES or not body or body != body.strip()
                or '\\' in body or body.startswith('/') or ':' in body
                or any(part in ('', '.', '..') for part in body.split('/'))):
            raise GuidanceProtocolError('Noncanonical/unsupported public change token')
        result.add(value)
    return sorted(result)


def _catalog(task_ids, pair_cost_seconds):
    if (not isinstance(task_ids, (list, tuple)) or not task_ids
            or any(not isinstance(t, str) or not t for t in task_ids)
            or len(set(task_ids)) != len(task_ids)):
        raise GuidanceProtocolError('A nonempty distinct public task catalog is required')
    if set(pair_cost_seconds) != set(task_ids):
        raise GuidanceProtocolError('One common paid cost estimate per public task is required')
    for value in pair_cost_seconds.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise GuidanceProtocolError('Costs must be positive finite measured estimates')
    return list(task_ids)


def paired_cost_profile(samples_by_task):
    """Frozen three-old-query estimator. Does not evaluate an answer."""
    result = {}
    for task, samples in samples_by_task.items():
        if not isinstance(samples, (list, tuple)) or len(samples) != 3:
            raise GuidanceProtocolError('Exactly three paid old-state query costs per task')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in samples):
            raise GuidanceProtocolError('Measured query costs must be positive and finite')
        result[task] = 2.0 * statistics.median(samples)
    _catalog(list(samples_by_task), result)
    return result


def checked_history(history, task_ids, trajectory_id, episode_index):
    """Return ALL earlier own positive events; late/nonregression pairs add no count."""
    if not isinstance(history, (list, tuple)):
        raise GuidanceProtocolError('History must consist of observed selected pair records')
    positive = []
    for event in history:
        if not isinstance(event, dict) or set(event) != HISTORY_FIELDS:
            raise GuidanceProtocolError('History schema excludes extra labels/features')
        if (event.get('source') != 'own_observed_paired_execution'
                or event.get('trajectory_id') != trajectory_id
                or event.get('selected') is not True):
            raise GuidanceProtocolError('Foreign, reference-derived or unselected history is forbidden')
        earlier = event.get('episode_index')
        if type(earlier) is not int or not 0 <= earlier < episode_index:
            raise GuidanceProtocolError('History must be strictly earlier than this decision')
        if event.get('task_id') not in task_ids or not is_sha(event.get('receipt_sha256')):
            raise GuidanceProtocolError('History requires a registered task and bound observed receipt')
        for field in ('timely', 'old_primary_pass', 'new_primary_pass'):
            if type(event.get(field)) is not bool:
                raise GuidanceProtocolError('History judgments and timeliness must be booleans')
        public_tokens = tokens(event.get('changed_tokens', []))
        if event['timely'] and event['old_primary_pass'] and not event['new_primary_pass']:
            positive.append({**event, 'changed_tokens': public_tokens})
    return positive


def checked_impact(impact, task_ids, changed_tokens, feature_block_id, episode_index):
    """Invalid/incomplete evidence broadens admission; source/future leakage rejects."""
    if impact is None:
        return list(task_ids), 'impact_evidence_unavailable'
    if not isinstance(impact, dict) or set(impact) != IMPACT_FIELDS:
        raise GuidanceProtocolError('Impact schema excludes extra labels/features')
    if (impact.get('source') != 'paid_old_native_contexts'
            or impact.get('feature_block_id') != feature_block_id
            or impact.get('episode_index') != episode_index
            or impact.get('predecision') is not True
            or impact.get('current_or_future_outcomes_used') is not False):
        raise GuidanceProtocolError('Impact evidence must be the matching predecision old-state block')
    admitted = impact.get('admitted_task_ids', [])
    if not isinstance(admitted, (list, tuple)) or len(set(admitted)) != len(admitted) or not set(admitted) <= set(task_ids):
        raise GuidanceProtocolError('Malformed impact candidate identities')
    if (not changed_tokens or impact.get('provenance_verified') is not True
            or not is_sha(impact.get('evidence_receipt_sha256'))
            or set(impact.get('task_ids', [])) != set(task_ids)
            or tokens(impact.get('changed_tokens', [])) != changed_tokens):
        return list(task_ids), 'impact_provenance_or_change_scope_incomplete'
    if not admitted:
        return list(task_ids), 'empty_old_trace_intersection_is_not_safe_skip_proof'
    if len(admitted) == len(task_ids):
        return list(task_ids), 'impact_admits_entire_catalog'
    return [task for task in task_ids if task in set(admitted)], 'valid_strict_subset_heuristic'


def rank_arm(task_ids, pair_cost_seconds, admitted_task_ids, history_counts, arm):
    """Unmodified v6 rank semantics for both fixed baselines and chosen arm."""
    if arm not in ARMS:
        raise GuidanceProtocolError('Unknown fixed arm')
    use_impact, use_history = ARMS[arm]
    candidates = admitted_task_ids if use_impact else task_ids
    return sorted(candidates, key=lambda task: (-history_counts.get(task, 0) if use_history else 0,
                                               pair_cost_seconds[task], task))


def choose(task_ids, pair_cost_seconds, impact, history, *, trajectory_id,
           feature_block_id, episode_index, changed_tokens, pair_limit):
    """Choose a fixed arm; the root runner still owns actual budgets/dispatch.

    Exact nominal K-prefix simplification is a prospective heuristic, not a
    guarantee about actual wall-time scheduling with noisy duration estimates.
    """
    task_ids = _catalog(task_ids, pair_cost_seconds)
    if type(episode_index) is not int or episode_index < 1 or type(pair_limit) is not int or pair_limit < 1:
        raise GuidanceProtocolError('Positive logical episode and pair ceiling required')
    if not trajectory_id or not feature_block_id:
        raise GuidanceProtocolError('Own trajectory and common paid feature block identities required')
    public_tokens = tokens(changed_tokens)
    positive = checked_history(history, task_ids, trajectory_id, episode_index)
    history_counts = dict(Counter(event['task_id'] for event in positive))
    compatible = bool(positive and public_tokens) and all(
        event['changed_tokens'] and set(event['changed_tokens']).intersection(public_tokens) for event in positive)
    admitted, impact_reason = checked_impact(impact, task_ids, public_tokens, feature_block_id, episode_index)
    selective = len(admitted) < len(task_ids)
    candidate = f'I{int(selective)}_H{int(compatible)}'
    candidate_order = rank_arm(task_ids, pair_cost_seconds, admitted, history_counts, candidate)
    candidate_prefix = candidate_order[:pair_limit]
    eligible = [arm for arm in SIMPLICITY_ORDER
                if (not ARMS[arm][0] or selective) and (not ARMS[arm][1] or compatible)]
    # Drop only enabled mechanisms, never introduce a mechanism rejected by a gate.
    matching = [arm for arm in eligible if
                rank_arm(task_ids, pair_cost_seconds, admitted, history_counts, arm)[:pair_limit] == candidate_prefix]
    chosen = min(matching, key=lambda arm: (sum(ARMS[arm]), SIMPLICITY_ORDER.index(arm)))
    order = rank_arm(task_ids, pair_cost_seconds, admitted, history_counts, chosen)
    reasons = [impact_reason]
    if not positive:
        reasons.append('no_own_timely_positive_history')
    elif not compatible:
        reasons.append('global_history_contains_unknown_or_change_incompatible_positive_event')
    else:
        reasons.append('all_own_positive_history_has_public_change_overlap')
    if chosen != candidate:
        reasons.append('simpler_arm_has_identical_nominal_K_prefix')
    clean_inputs = {'task_ids': task_ids, 'pair_cost_seconds': pair_cost_seconds,
        'impact': impact, 'history': history, 'trajectory_id': trajectory_id,
        'feature_block_id': feature_block_id, 'episode_index': episode_index,
        'changed_tokens': public_tokens, 'pair_limit': pair_limit}
    return {'guidance_version': VERSION, 'candidate_arm': candidate, 'chosen_arm': chosen,
        'impact_eligible': selective, 'global_history_eligible': compatible,
        'nominal_ordered_task_ids': order, 'nominal_prefix_task_ids': order[:pair_limit],
        'paired_attempt_ceiling': pair_limit, 'all_positive_history_counts': history_counts,
        'reasons': reasons, 'predecision_input_sha256': digest(clean_inputs),
        'uses_reference_or_current_new_outcomes': False,
        'new_untested_guidance_rule': True, 'performance_or_safety_guaranteed': False}

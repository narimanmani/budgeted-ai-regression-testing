"""Four prospectively selected LIVE cold-start confirmation cells.

These use actual fresh native executions, not the recorded-outcome replay bank.
They cover the first A change only and exact operational contract checking.
The long-history factorial remains an explicitly separate replay experiment.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import time

from experiment.transfer_v9.common import HERE, ROOT, GUIDANCE, GUIDANCE_SHA, read, save, sha, digest


def guidance():
    if sha(GUIDANCE) != GUIDANCE_SHA:
        raise RuntimeError('Original guidance changed')
    spec = importlib.util.spec_from_file_location('cg1_live_v9', GUIDANCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame_row(setting, method, role, state, task, case_id, sample=0):
    prefix = 'cg1' if method == 'CG1' else method
    ident = (f'live-{setting}-{prefix}-profile-p{sample}-{task}' if role == 'live_profile' else
             f'live-{setting}-{prefix}-pair-{task}-'+('old' if state == 'H' else 'new'))
    return {'operation_id': ident,
            'task_id': task, 'state': state, 'case_id': case_id,
            'pass_index': sample, 'frame_role': role}


def public_features(profile_records, task_ids):
    """A deliberate whitelist: no contract verdict or current/future observation."""
    result = {}
    for task in task_ids:
        rows = [r for r in profile_records if r['task_id'] == task]
        if len(rows) != 3 or any(r['state'] != 'H' for r in rows):
            raise RuntimeError('Exactly three fresh OLD costs/contexts per task are required')
        result[task] = [{'elapsed_seconds': r['elapsed_seconds'],
                         'observed_dependency_tokens': r['observed_dependency_tokens'],
                         'receipt_sha256': r['receipt_sha256']} for r in rows]
    return result


def run_setting(run, ledger, setting, *, client=None, worker_pool=None):
    # Delayed import prevents any native factory from importing this driver
    # during ordinary source-only schema/unit checks.
    from experiment.transfer_v9.collect import acquire, CASES, CHANGES
    run = Path(run)
    plan = read(HERE/'cohorts/LIVE_CONFIRMATION_PLAN.json')
    if setting not in ('vanna', 'rasa') or plan['fixed_conditions']['whole_native_request_ceiling_per_arm'] != 28:
        raise RuntimeError('Unexpected predeclared live confirmation design')
    task_ids = [t['task_id'] for t in read(HERE/f'cohorts/validation/{setting}.private.json')['tasks']]
    guide = guidance()
    results = []
    for method in ('CG1', 'budgeted_retest_all'):
        directory = run/'validation/live-policy'/setting/method
        directory.mkdir(parents=True, exist_ok=False)
        case_id = CASES[setting][0]
        profiles = []
        cpu_started = time.process_time_ns()
        if method == 'CG1':
            frame = [frame_row(setting, method, 'live_profile', 'H', task, case_id, sample)
                     for sample in range(3) for task in task_ids]
            # Real acquisition is outside the controller CPU timer below.
            cpu_before = (time.process_time_ns()-cpu_started)/1e9
            profiles = acquire(run, ledger, 'validation', setting, frame, client, worker_pool)
            cpu_started = time.process_time_ns()
            public = public_features(profiles, task_ids)
            pair_costs = guide.paired_cost_profile({task: [s['elapsed_seconds'] for s in samples]
                                                  for task, samples in public.items()})
            changed = CHANGES[setting]['A']
            admitted = [task for task in task_ids if any(set(s['observed_dependency_tokens']).intersection(changed)
                                                       for s in public[task])]
            feature_id = digest({'trajectory': f'live-{setting}-{method}', 'public_profiles': public})
            impact = {'source': 'paid_old_native_contexts', 'feature_block_id': feature_id,
                'episode_index': 1, 'predecision': True, 'current_or_future_outcomes_used': False,
                'provenance_verified': True, 'task_ids': task_ids, 'admitted_task_ids': admitted,
                'changed_tokens': changed, 'evidence_receipt_sha256': digest(public)}
            inputs = {'task_ids': task_ids, 'pair_cost_seconds': pair_costs, 'impact': impact,
                'history': [], 'trajectory_id': f'live-{setting}-{method}', 'feature_block_id': feature_id,
                'episode_index': 1, 'changed_tokens': changed, 'pair_limit': (28-len(profiles))//2}
            choice = guide.choose(**inputs)
            selected = choice['nominal_prefix_task_ids']
        else:
            cpu_before = 0
            public, inputs = {}, None
            selected = task_ids[:min(len(task_ids), 28//2)]
            choice = {'method': method, 'nominal_prefix_task_ids': selected,
                      'reference_or_current_new_outcomes_used': False, 'paid_profile_requests': 0}
        cpu_seconds = cpu_before+(time.process_time_ns()-cpu_started)/1e9
        predecision = {'method': method, 'setting_id': setting, 'case_id': case_id,
            'native_request_ceiling': 28, 'guidance_sha256': GUIDANCE_SHA,
            'actual_profile_operation_ids': [r['record_id'] for r in profiles],
            'public_old_features': public, 'guidance_inputs': inputs, 'decision': choice,
            'reference_or_current_new_outcomes_used': False, 'history_initially_empty': True,
            'controller_cpu_seconds': cpu_seconds,
            'written_before_any_current_bad_state_call_in_this_cell': True}
        save(directory/'PREDECISION.json', predecision)
        pairs_frame = [frame_row(setting, method, 'live_selected', state, task, case_id)
                       for task in selected for state in ('H', 'A')]
        for row in pairs_frame:
            row['predecision_sha256'] = sha(directory/'PREDECISION.json')
        pairs = acquire(run, ledger, 'validation', setting, pairs_frame, client, worker_pool)
        by_cell = {(r['task_id'], r['state']): r for r in pairs}
        outcomes = []
        for task in selected:
            old, new = by_cell[(task, 'H')], by_cell[(task, 'A')]
            outcomes.append({'task_id': task, 'old_record_id': old['record_id'], 'new_record_id': new['record_id'],
                'old_contract_pass': old['contract_pass'], 'new_contract_pass': new['contract_pass'],
                'observed_contract_regression': old['contract_pass'] and not new['contract_pass'],
                'old_receipt_sha256': old['receipt_sha256'], 'new_receipt_sha256': new['receipt_sha256']})
        count = len(profiles)+len(pairs)
        if count > 28:
            raise RuntimeError('Live complete-cost native request ceiling exceeded')
        result = {'setting_id': setting, 'method': method, 'case_id': case_id,
            'native_request_ceiling': 28, 'actual_profile_native_requests': len(profiles),
            'actual_selected_native_requests': len(pairs), 'actual_total_native_requests': count,
            'unused_native_request_allowance': 28-count,
            'observed_contract_regression_pairs': sum(o['observed_contract_regression'] for o in outcomes),
            'selected_task_ids': selected, 'outcomes': outcomes,
            'records': profiles+pairs, 'predecision_path': (directory/'PREDECISION.json').relative_to(ROOT).as_posix(),
            'predecision_sha256': sha(directory/'PREDECISION.json'),
            'allocated_native_and_checker_feature_wall_seconds': sum(r['elapsed_seconds']+r['checker_seconds']+r['feature_seconds'] for r in profiles+pairs),
            'controller_cpu_seconds': cpu_seconds,
            'platform_state_preparation': 'shared already prepared validation platform; setup measured separately, no free model calls',
            'operational_checker': 'exact frozen contract', 'initial_history': 'empty',
            'physically_executed_not_counterfactual_replay': True,
            'new_independent_case_or_change_sequence': False,
            'not_a_live_test_of_long_history_or_checker_noise': True}
        save(directory/'RESULT.json', result)
        results.append(result)
    return results

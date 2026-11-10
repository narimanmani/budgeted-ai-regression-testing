"""Pure v8 admission and development-selection gates; no native dispatch.

The caller must freeze original inputs, runtime configuration and these checks
before the corresponding observations. Development candidates never receive a
policy result as a selection input. Saved native receipts are rechecked here.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

from experiment.native_v3.common.contracts import operational_check
from experiment.native_v3.common.reference import reference_check

STATES = ('HEALTHY', 'A_BAD', 'B_BAD')
CANDIDATES = ('P0', 'P1')
POLICY_SHA256 = 'f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989'


class ProtocolError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def budget_projection():
    """Prospective maximum query units; allocated scenario costs are not added."""
    apps, repetitions, tasks, arms, regimes = 2, 2, 8, 5, 2
    blocks = apps * repetitions
    trajectories = blocks * arms * regimes * 2
    development = apps * len(CANDIDATES) * len(STATES) * tasks * 2
    qualification = apps * (tasks + 4 + 4) * 2
    reference = apps * len(STATES) * tasks * 2
    profiles = blocks * 2 * tasks * 3
    own_warm = blocks * arms * 2 * tasks * 2
    comparisons = blocks * arms * regimes * (2 + 4) * 3 * 2
    main = profiles + own_warm + comparisons
    total = development + qualification + reference + main
    return {
        'development': development, 'qualification': qualification,
        'reference': reference, 'main_old_profiles': profiles,
        'main_own_warm_calibration': own_warm,
        'main_selected_comparisons': comparisons,
        'main': main, 'main_per_application_repetition': main // blocks,
        'trajectories': trajectories, 'planned_scientific_units': total,
        'planned_reserved_provider_probes': 3,
        'prior_native_units': 2071, 'shared_cap': 5000,
        'new_phase_cap': 2929,
        'remaining_slack_after_science_and_planned_probes': 5000 - 2071 - total - 3,
    }


def _frame(task_ids, witnesses, controls, bad_subsets, mode):
    if (len(task_ids) != 8 or len(set(task_ids)) != 8
            or any(not isinstance(t, str) or not t for t in task_ids)):
        raise ProtocolError('The fixed distinct eight-task catalog is required')
    if mode not in ('development', 'qualification', 'reference'):
        raise ProtocolError('Unregistered acquisition mode')
    for state in ('A_BAD', 'B_BAD'):
        subset, control = bad_subsets[state], controls[state]
        if (len(subset) != 4 or len(set(subset)) != 4
                or not set(subset) <= set(task_ids)
                or witnesses[state] not in subset
                or len(control) != 2 or len(set(control)) != 2
                or not set(control) <= set(subset)
                or witnesses[state] in control):
            raise ProtocolError('Predeclared witnesses, subsets or controls malformed')
    chosen = {'HEALTHY': list(task_ids)}
    chosen.update({state: list(task_ids) if mode != 'qualification' else list(bad_subsets[state])
                   for state in ('A_BAD', 'B_BAD')})
    return {(state, task, repeat) for state, tasks in chosen.items()
            for task in tasks for repeat in (1, 2)}


def evaluate_cells(*, task_ids, witnesses, controls, bad_subsets, cells, mode,
                   application_id, cohort_id, prompt_id):
    """Apply the fixed truth gate to authenticated, independently scored cells."""
    required = _frame(task_ids, witnesses, controls, bad_subsets, mode)
    seen = {}
    for row in cells:
        key = row['state_id'], row['task_id'], row['repetition']
        if (key in seen or key not in required or type(row['primary_pass']) is not bool
                or type(row['repetition']) is not int):
            raise ProtocolError('Duplicate, foreign or malformed acquisition cell')
        seen[key] = row['primary_pass']
    if set(seen) != required:
        raise ProtocolError('Complete exact state/task/pass frame required')
    requirements = [
        {'state': 'HEALTHY', 'task': task, 'pass': repeat,
         'expected': True, 'actual': seen['HEALTHY', task, repeat]}
        for task in task_ids for repeat in (1, 2)
    ]
    for state in ('A_BAD', 'B_BAD'):
        for repeat in (1, 2):
            requirements.append({'state': state, 'task': witnesses[state], 'pass': repeat,
                                 'expected': False, 'actual': seen[state, witnesses[state], repeat]})
            requirements.extend({'state': state, 'task': task, 'pass': repeat,
                                 'expected': True, 'actual': seen[state, task, repeat]}
                                for task in controls[state])
    violations = [row for row in requirements if row['expected'] != row['actual']]
    return {
        'application_id': application_id, 'cohort_id': cohort_id,
        'prompt_id': prompt_id, 'mode': mode, 'complete': True,
        'passed': not violations, 'outputs': len(seen),
        'healthy_primary_passes': sum(value for key, value in seen.items() if key[0] == 'HEALTHY'),
        'healthy_outputs': 16, 'primary_passes': sum(seen.values()),
        'required_conditions': len(requirements), 'violated_conditions': violations,
        'all_observed_state_pass_counts': dict(Counter(state for (state, task, repeat), value in seen.items() if value)),
        'guidance_or_policy_outcomes_used': False,
    }


def gate_saved_acquisition(directory, *, application_id, cohort_id, prompt_id,
                           prompt_text_sha256, input_freeze_sha256, mode,
                           task_ids, contract_document, witnesses, controls,
                           bad_subsets):
    """Recheck actual saved native/root/primary identities without new queries.

    The runtime's cohort/prompt/input provenance is mandatory. The caller retains
    source and actual-context audit as a separate prerequisite; source metadata
    remains supplementary to the factual primary judgment.
    """
    directory = Path(directory).resolve()
    completion = read(directory/'REFERENCE_COMPLETION.json')
    required = _frame(task_ids, witnesses, controls, bad_subsets, mode)
    if (completion.get('phase') != mode or completion.get('error') is not None
            or completion.get('outputs') != len(required)
            or completion.get('planned_outputs') != len(required)):
        raise ProtocolError('Declared acquisition incomplete or wrong role')
    contract_rows = contract_document['contracts']
    contracts = {row['id']: row for row in contract_rows}
    if set(contracts) != set(task_ids) or len(contracts) != 8 or len(contract_rows) != 8:
        raise ProtocolError('Contract catalog differs from the fixed task catalog')
    cells = []
    evidence = []
    for line in (directory/'sealed/reference_outputs.jsonl').read_text(encoding='utf-8-sig').splitlines():
        row = json.loads(line)
        path = Path(row['receipt_path']).resolve()
        if not path.is_relative_to(directory) or sha(path) != row['receipt_sha256']:
            raise ProtocolError('Raw acquisition receipt changed or is outside its directory')
        raw = read(path)
        native, receipt = raw['native_output'], raw['root_meter_receipt']
        reservation = receipt.get('native_reservation') or {}
        metadata = reservation.get('metadata') or {}
        expected_scope = {'cohort_id': cohort_id, 'prompt_candidate_id': prompt_id,
                          'prompt_text_sha256': prompt_text_sha256,
                          'input_freeze_sha256': input_freeze_sha256}
        for field, expected in expected_scope.items():
            if any(record.get(field) != expected for record in (row, raw, metadata, native)):
                raise ProtocolError('Index/wrapper/native/reservation cohort/configuration scope differs')
        for field in ('request_id', 'state_id', 'task_id'):
            if (row.get(field) != raw.get(field) or native.get(field) != raw.get(field)
                    or metadata.get(field) != raw.get(field)):
                raise ProtocolError('Native/wrapper/index/reservation identities differ')
        if (raw.get('application_id') != application_id or raw.get('phase') != mode
                or metadata.get('application_id') != application_id or metadata.get('phase') != mode
                or native.get('valid_native_response') is not True
                or receipt.get('dispatch_safe_to_continue') is not True
                or receipt.get('native_query_units_reserved') != 1
                or receipt.get('provider_join', {}).get('joined') is not True
                or reservation.get('request_id') != raw['request_id']
                or receipt.get('allocation_id') != raw['request_id']):
            raise ProtocolError('Wrong cohort/configuration/role or unsafe native cost join')
        spec = contracts[row['task_id']]
        contract = {'id': spec['id'], 'version': spec['data_version'],
                    'expected_behavior': 'answer', 'accepted_answers': spec['accepted_values']}
        output = {'answer': native.get('answer'), 'completed': native.get('completed') is True,
                  'sources': []}
        operational = operational_check(output, contract)['passed']
        independent = reference_check(output, contract)['passed']
        if operational != independent or independent != row['reference_check']['primary_pass']:
            raise ProtocolError('Saved primary judgment differs from unchanged independent checkers')
        cells.append({'state_id': row['state_id'], 'task_id': row['task_id'],
                      'repetition': row['repetition'], 'primary_pass': independent})
        evidence.append({'request_id': raw['request_id'], 'receipt_sha256': row['receipt_sha256']})
    result = evaluate_cells(task_ids=task_ids, witnesses=witnesses, controls=controls,
                            bad_subsets=bad_subsets, cells=cells, mode=mode,
                            application_id=application_id, cohort_id=cohort_id,
                            prompt_id=prompt_id)
    result.update({'rechecked_raw_evidence': evidence,
                   'completion_sha256': sha(directory/'REFERENCE_COMPLETION.json'),
                   'new_native_or_model_queries': 0})
    return result


def select_development_candidate(results, *, application_id, cohort_id):
    """Choose the first eligible fixed candidate after both complete frames."""
    if set(results) != set(CANDIDATES):
        raise ProtocolError('Both predeclared candidate frames must be retained before selection')
    for candidate in CANDIDATES:
        result = results[candidate]
        if (result.get('application_id') != application_id or result.get('cohort_id') != cohort_id
                or result.get('prompt_id') != candidate or result.get('mode') != 'development'
                or result.get('complete') is not True or result.get('outputs') != 48
                or result.get('guidance_or_policy_outcomes_used') is not False
                or type(result.get('passed')) is not bool
                or result.get('passed') != (not bool(result.get('violated_conditions')))):
            raise ProtocolError('Development selection requires complete uncontaminated candidate frames')
    chosen = next((candidate for candidate in CANDIDATES if results[candidate]['passed']), None)
    return {'application_id': application_id, 'cohort_id': cohort_id,
            'selected_prompt_id': chosen,
            'status': 'READY_TO_FREEZE_FRESH_VALIDATION' if chosen else 'STOP_NO_ELIGIBLE_DEVELOPMENT_CONFIGURATION',
            'candidate_order': list(CANDIDATES),
            'selection_rule': 'First eligible in the prospectively fixed P0,P1 order; no maximization of failures or policy benefit',
            'guidance_or_policy_outcomes_used': False,
            'fresh_validation_answers_seen_during_selection': 0}

from copy import deepcopy
import pytest

from experiment.development_v8.protocol.gates import (
    ProtocolError, budget_projection, evaluate_cells, select_development_candidate,
    gate_saved_acquisition, sha,
)
import json

TASKS = [f'T{i:02d}' for i in range(1, 9)]
WITNESSES = {'A_BAD': 'T01', 'B_BAD': 'T03'}
CONTROLS = {state: ['T05', 'T06'] for state in ('A_BAD', 'B_BAD')}
SUBSETS = {'A_BAD': ['T01', 'T02', 'T05', 'T06'], 'B_BAD': ['T03', 'T04', 'T05', 'T06']}

def cells(mode='development'):
    return [{'state_id': state, 'task_id': task, 'repetition': repeat,
             'primary_pass': not (state in WITNESSES and task == WITNESSES[state])}
            for state in ('HEALTHY', 'A_BAD', 'B_BAD')
            for task in (SUBSETS[state] if state != 'HEALTHY' and mode == 'qualification' else TASKS)
            for repeat in (1, 2)]

def gate(data=None, mode='development', prompt='P0'):
    return evaluate_cells(task_ids=TASKS, witnesses=WITNESSES, controls=CONTROLS,
                          bad_subsets=SUBSETS, cells=cells(mode) if data is None else data,
                          mode=mode, application_id='dify', cohort_id='development', prompt_id=prompt)

def test_complete_development_and_qualification_frames():
    assert gate()['passed'] and gate()['outputs'] == 48
    assert gate(mode='qualification')['passed'] and gate(mode='qualification')['outputs'] == 32
    assert gate()['required_conditions'] == 28

def test_budget_accounts_all_physical_acquisitions():
    value = budget_projection()
    assert value['planned_scientific_units'] == 2624
    assert value['main'] == 2272 and value['main_per_application_repetition'] == 568
    assert value['main_own_warm_calibration'] == 640 and value['main_old_profiles'] == 192
    assert value['remaining_slack_after_science_and_planned_probes'] == 302

@pytest.mark.parametrize('index', [0, 16, 32])
def test_missing_state_cells_cannot_pass(index):
    data = cells(); data.pop(index)
    with pytest.raises(ProtocolError): gate(data)

def test_duplicate_cells_cannot_pass():
    data = cells(); data[-1] = deepcopy(data[0])
    with pytest.raises(ProtocolError): gate(data)

def test_healthy_failure_blocks_gate():
    data = cells(); data[0]['primary_pass'] = False
    assert not gate(data)['passed']

def test_fault_witness_must_fail_both_passes():
    data = cells()
    next(row for row in data if row['state_id'] == 'B_BAD' and row['task_id'] == 'T03')['primary_pass'] = True
    assert not gate(data)['passed']

def test_unaffected_controls_must_remain_correct():
    data = cells()
    next(row for row in data if row['state_id'] == 'A_BAD' and row['task_id'] == 'T05')['primary_pass'] = False
    assert not gate(data)['passed']

def test_first_eligible_candidate_wins_without_fault_count_ranking():
    first, second = gate(prompt='P0'), gate(prompt='P1')
    second['primary_passes'] = 1
    selected = select_development_candidate({'P0': first, 'P1': second}, application_id='dify', cohort_id='development')
    assert selected['selected_prompt_id'] == 'P0'

def test_second_candidate_can_be_selected_only_if_first_ineligible():
    data = cells(); data[0]['primary_pass'] = False
    first = gate(data, prompt='P0')
    selected = select_development_candidate({'P0': first, 'P1': gate(prompt='P1')}, application_id='dify', cohort_id='development')
    assert selected['selected_prompt_id'] == 'P1'

def test_both_fail_is_bounded_stop():
    data = cells(); data[0]['primary_pass'] = False
    first, second = gate(data, prompt='P0'), gate(data, prompt='P1')
    selected = select_development_candidate({'P0': first, 'P1': second}, application_id='dify', cohort_id='development')
    assert selected['selected_prompt_id'] is None and selected['status'].startswith('STOP_')

def test_incomplete_candidate_set_cannot_be_selected():
    with pytest.raises(ProtocolError):
        select_development_candidate({'P0': gate()}, application_id='dify', cohort_id='development')

def test_policy_contamination_cannot_enter_development_selection():
    first = gate(prompt='P0'); first['guidance_or_policy_outcomes_used'] = True
    with pytest.raises(ProtocolError):
        select_development_candidate({'P0': first, 'P1': gate(prompt='P1')}, application_id='dify', cohort_id='development')

def test_boolean_pass_index_is_not_an_integer_repetition():
    data = cells(); data[0]['repetition'] = True
    with pytest.raises(ProtocolError): gate(data)

def test_inconsistent_gate_summary_cannot_select_candidate():
    first = gate(prompt='P0'); first['passed'] = False
    with pytest.raises(ProtocolError):
        select_development_candidate({'P0': first, 'P1': gate(prompt='P1')}, application_id='dify', cohort_id='development')

def saved_frame(tmp_path):
    directory = tmp_path/'acquisition'; (directory/'raw').mkdir(parents=True)
    (directory/'sealed').mkdir()
    contracts = {'contracts': [{'id': task, 'data_version': 'v1', 'accepted_values': ['GOOD_'+task]} for task in TASKS]}
    lines = []
    for i, cell in enumerate(cells(), 1):
        state, task = cell['state_id'], cell['task_id']; request = 'request-'+str(i)
        meta = {'application_id': 'dify', 'phase': 'development', 'request_id': request,
                'state_id': state, 'task_id': task, 'cohort_id': 'development',
                'prompt_candidate_id': 'P0', 'prompt_text_sha256': 'a'*64,
                'input_freeze_sha256': 'b'*64}
        native = {'request_id': request, 'state_id': state, 'task_id': task,
                  'cohort_id': 'development', 'prompt_candidate_id': 'P0',
                  'prompt_text_sha256': 'a'*64, 'input_freeze_sha256': 'b'*64,
                  'valid_native_response': True, 'completed': True,
                  'answer': 'GOOD_'+task if cell['primary_pass'] else 'BAD'}
        receipt = {'allocation_id': request, 'native_query_units_reserved': 1,
                   'dispatch_safe_to_continue': True, 'provider_join': {'joined': True},
                   'native_reservation': {'request_id': request, 'metadata': meta}}
        raw = {**meta, 'native_output': native, 'root_meter_receipt': receipt}
        path = directory/'raw'/f'{i:03d}.json'; path.write_text(json.dumps(raw), encoding='utf-8')
        row = {**meta, 'repetition': cell['repetition'], 'receipt_path': str(path),
               'receipt_sha256': sha(path), 'reference_check': {'primary_pass': cell['primary_pass']}}
        lines.append(row)
    index = directory/'sealed/reference_outputs.jsonl'
    index.write_text(''.join(json.dumps(row)+'\n' for row in lines), encoding='utf-8')
    (directory/'REFERENCE_COMPLETION.json').write_text(json.dumps({'phase': 'development',
        'error': None, 'outputs': 48, 'planned_outputs': 48}), encoding='utf-8')
    kwargs = dict(application_id='dify', cohort_id='development', prompt_id='P0',
                  prompt_text_sha256='a'*64, input_freeze_sha256='b'*64,
                  mode='development', task_ids=TASKS, contract_document=contracts,
                  witnesses=WITNESSES, controls=CONTROLS, bad_subsets=SUBSETS)
    return directory, lines, kwargs

def test_actual_saved_receipts_are_independently_rechecked(tmp_path):
    directory, rows, kwargs = saved_frame(tmp_path)
    result = gate_saved_acquisition(directory, **kwargs)
    assert result['passed'] and result['outputs'] == 48 and len(result['rechecked_raw_evidence']) == 48

@pytest.mark.parametrize('field', ['task_id', 'cohort_id', 'prompt_candidate_id', 'input_freeze_sha256'])
def test_foreign_native_identity_or_configuration_rejected(tmp_path, field):
    directory, rows, kwargs = saved_frame(tmp_path)
    path = directory/'raw/001.json'; raw = json.loads(path.read_text(encoding='utf-8'))
    raw['native_output'][field] = 'foreign'; path.write_text(json.dumps(raw), encoding='utf-8')
    rows[0]['receipt_sha256'] = sha(path)
    (directory/'sealed/reference_outputs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
    with pytest.raises(ProtocolError): gate_saved_acquisition(directory, **kwargs)

def test_changed_saved_primary_flag_cannot_pass(tmp_path):
    directory, rows, kwargs = saved_frame(tmp_path)
    rows[0]['reference_check']['primary_pass'] = False
    (directory/'sealed/reference_outputs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
    with pytest.raises(ProtocolError): gate_saved_acquisition(directory, **kwargs)

def test_foreign_root_reserved_scope_cannot_pass(tmp_path):
    directory, rows, kwargs = saved_frame(tmp_path)
    path = directory/'raw/001.json'; raw = json.loads(path.read_text(encoding='utf-8'))
    raw['root_meter_receipt']['native_reservation']['metadata']['prompt_candidate_id'] = 'P1'
    path.write_text(json.dumps(raw), encoding='utf-8'); rows[0]['receipt_sha256'] = sha(path)
    (directory/'sealed/reference_outputs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
    with pytest.raises(ProtocolError): gate_saved_acquisition(directory, **kwargs)

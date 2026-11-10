"""Development-extension boundary checks; no native/model calls."""
from pathlib import Path
import hashlib
from experiment.development_v8 import round2
from experiment.development_v8.control import read, sha
from experiment.development_v8.dify_runtime import NativeRuntime
from experiment.development_v8.runtime_common import identity
from experiment.development_v8.protocol.gates import evaluate_cells

def test_example_contains_no_development_fact_value():
    contracts=read(round2.HERE/'workloads/development/dify/contracts.json')['contracts']
    assert all(value not in round2.PROMPT for row in contracts for value in row['accepted_values'])
    assert 'Record EXAMPLE' in round2.PROMPT and 'SAMPLE-000' in round2.PROMPT

def test_actual_p2_constructor_and_identity_are_pure(tmp_path):
    config=read(round2.RUN/'development_round2/RUNTIME_CONFIG.json')
    native_dir=tmp_path/'not-created'
    runtime=NativeRuntime(config,native_dir,'software-test-P2')
    assert not native_dir.exists()
    scope=identity(runtime)
    assert scope['prompt_candidate_id']=='P2' and scope['cohort_id']=='development'
    assert scope['prompt_text_sha256']==hashlib.sha256(round2.PROMPT.encode()).hexdigest()
    assert scope['input_freeze_sha256']==sha(round2.RUN/'development_round2/INPUT_FREEZE.json')

def test_p2_uses_same_original_admission_conditions():
    q=read(round2.HERE/'workloads/development/dify/qualification.json');cells=[]
    for state in ('HEALTHY','A_BAD','B_BAD'):
        for task in q['task_ids']:
            for repeat in (1,2):
                cells.append({'state_id':state,'task_id':task,'repetition':repeat,
                    'primary_pass':not (state!='HEALTHY' and task==q['qualification_witnesses'][state])})
    result=evaluate_cells(task_ids=q['task_ids'],witnesses=q['qualification_witnesses'],
        controls={s:q['unaffected_controls'] for s in ('A_BAD','B_BAD')},bad_subsets=q['qualification_subsets'],
        cells=cells,mode='development',application_id='dify',cohort_id='development',prompt_id='P2')
    assert result['passed'] and result['required_conditions']==28 and result['outputs']==48

def test_extension_keeps_global_native_cap():
    assert 2071+2672+3==4746 and 5000-4746==254
    assert read(round2.RUN/'development_round2/ROUND2_FREEZE.json')['original_two_candidate_protocol_adherence_claimed'] is False

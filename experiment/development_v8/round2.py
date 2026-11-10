"""One separately declared adaptive development extension; old protocol is retained.

The extension changes only a generic native instruction, using the same Dify
development workload. No validation answer or policy outcome may precede it.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
from experiment.development_v8.control import Campaign, read, sha, write_new
from experiment.development_v8.acquisition import MeteredApplication, acquire
from experiment.development_v8.run_acquisition import prepare_dify
from experiment.development_v8.dify_runtime import NativeRuntime
from experiment.development_v8.protocol.gates import gate_saved_acquisition
from experiment.validation_v7.execution.runner import FrozenGuidanceGuard
from experiment.validation_v7.execution.source_channels import CanonicalContracts

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'experiment/runs/development_v8_20261101'
PROMPT=("Use only the retrieved records to answer the actual question. Find its exact record identifier, "
    "then copy the complete access label inside that record's square brackets. Output the label alone, without brackets.\n"
    "Formatting example (invented demonstration, not a retrieved record):\n"
    "Record: Record EXAMPLE access label [SAMPLE-000] additional notes\n"
    "Question: What is the access label for record EXAMPLE?\n"
    "Answer: SAMPLE-000\n"
    "For the actual question, preserve every character and internal space in its label. "
    "Do not copy the square brackets or any words outside them. Do not add an explanation. "
    "If the matching record or complete label is absent, output UNKNOWN.")

def _no_validation():
    rows=[json.loads(s) for s in (RUN/'native_reservations.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    if any(r['metadata']['phase'] not in ('development','setup_probe') for r in rows):
        raise RuntimeError('Adaptive development requires all validation/policy answers still unobserved')
    return len(rows)

def declare():
    prior=read(RUN/'DEVELOPMENT_SELECTION.json')
    if prior['status']!='STOP_NO_ELIGIBLE_DEVELOPMENT_CONFIGURATION' or prior['selected_prompt_by_application']!={'openwebui':'P0','dify':None}:
        raise RuntimeError('Round1 must be explicitly closed with its unchanged failed Dify decision')
    before=_no_validation()
    old=read(RUN/'DEVELOPMENT_FREEZE.json')
    for name,expected in old['files_sha256'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Original frozen development bytes changed')
    directory=RUN/'development_round2';directory.mkdir(exist_ok=False)
    prompt_sha=hashlib.sha256(PROMPT.encode()).hexdigest()
    prompt_file=directory/'P2_PROMPT.json';write_new(prompt_file,{'id':'P2','prompt_text':PROMPT,'prompt_text_sha256':prompt_sha,
        'example_is_invented_and_contains_no_development_or_validation_gold':True})
    mapping={**old['files_sha256'],str(Path(__file__).resolve().relative_to(ROOT)).replace('\\','/'):sha(Path(__file__)),
        str(prompt_file.relative_to(ROOT)).replace('\\','/'):sha(prompt_file),
        str((RUN/'DEVELOPMENT_SELECTION.json').relative_to(ROOT)).replace('\\','/'):sha(RUN/'DEVELOPMENT_SELECTION.json')}
    input_file=directory/'INPUT_FREEZE.json'
    write_new(input_file,{'cohort_id':'development','prompt_id':'P2','prompt_text_sha256':prompt_sha,
        'files_sha256':mapping,'same_development_data_intentionally_reused':True,'validation_answers_observed':0})
    config=directory/'RUNTIME_CONFIG.json'
    write_new(config,{'allow_native':True,'runtime_authorization_file':str(RUN/'RUNTIME_AUTH.json'),
        'cohort_dir':str(HERE/'workloads/development/dify'),'cohort_id':'development','prompt_id':'P2','prompt_text':PROMPT,
        'input_freeze_file':str(input_file),'input_freeze_sha256':sha(input_file),
        'receipt_scope':'round2-development-P2','scope_id':'development-P2','allow_new_dataset_scope':True,'rag_top_k':20})
    auth=read(RUN/'CAMPAIGN_AUTH.json');tasks=read(HERE/'workloads/development/dify/tasks.json')['tasks']
    stage=directory/'STAGE_AUTHORITY.json'
    write_new(stage,{'phase':'EXTERNAL_V8','stage_id':'development_round2_dify_P2','authorized':True,
        'campaign_auth_sha256':sha(RUN/'CAMPAIGN_AUTH.json'),'expires_at_epoch':auth['expires_at_epoch'],
        'allowed_states':['HEALTHY','A_BAD','B_BAD'],'allowed_tasks':[r['id'] for r in tasks],
        'allowed_metadata_phases':['development'],'native_query_cap':48,
        'input_freeze_sha256':sha(input_file),'prompt_text_sha256':prompt_sha})
    files=[ROOT/name for name in mapping]+[input_file,config,stage]
    write_new(directory/'ROUND2_FREEZE.json',{
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'phase':'EXTERNAL_V8','formal_registration':False,
        'status':'ONE_CANDIDATE_ADAPTIVE_DEVELOPMENT_EXTENSION_BEFORE_HELDOUT_ANSWERS',
        'round1_closed_decision_sha256':sha(RUN/'DEVELOPMENT_SELECTION.json'),
        'original_development_freeze_sha256':sha(RUN/'DEVELOPMENT_FREEZE.json'),
        'adaptation_basis':'Development showed label-preserving output-span/format failures. Add a generic invented formatting example; no source/expected values or policy results guide the example.',
        'original_two_candidate_protocol_adherence_claimed':False,
        'original_protocol_data_prompts_judgments_and_results_modified':False,
        'additional_candidate_order':['P2'],'additional_native_questions':48,
        'stopping_rule':'Run the complete 48-question development frame once. Select P2 only if all original admission conditions hold; otherwise stop this extension and the planned comparison. No further candidate in this extension.',
        'native_queries_reserved_before_extension':before,'fresh_validation_answers_before_extension':0,'policy_outcomes_before_extension':0,
        'new_total_scientific_projection':2672,'planned_provider_probes':3,'projected_cumulative_native_units':4746,
        'remaining_global_native_slack_after_complete_design':254,'shared_native_cap':5000,'shared_generation_cap_seconds':43200,
        'fresh_validation_data': 'Exactly the precommitted v8 bytes; no answer has been acquired and no case is revised.',
        'files_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(set(files))}})
    print('Declared one48-query adaptive development extension; original failed round retained.')

def run():
    directory=RUN/'development_round2';freeze_path=directory/'ROUND2_FREEZE.json';freeze=read(freeze_path)
    _no_validation()
    for name,expected in freeze['files_sha256'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Extension source/input bytes changed')
    output=RUN/'development-dify-P2';output.mkdir(exist_ok=False)
    config=read(directory/'RUNTIME_CONFIG.json');input_path=directory/'INPUT_FREEZE.json'
    runtime=NativeRuntime(config,RUN/'dify-platform','dify-development-P2')
    scope={'cohort_id':'development','prompt_candidate_id':'P2','prompt_text_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
        'input_freeze_sha256':sha(input_path)}
    guard=FrozenGuidanceGuard(additional_source_files=[ROOT/name for name in freeze['files_sha256']]+[freeze_path])
    write_new(output/'ACQUISITION_SOURCE_FREEZE.json',{'application_id':'dify','mode':'development',**scope,
        'round2_freeze_sha256':sha(freeze_path),'files_sha256':guard.implementation_sha256})
    campaign=None;meter=None;error=None;result=None;gate=None
    try:
        campaign=Campaign(RUN/'CAMPAIGN_AUTH.json',RUN,RUN/'INFRASTRUCTURE_AUTH.json')
        meter=MeteredApplication(runtime,campaign,output/'meter','dify',102,scope)
        prepare_dify(meter);campaign.close()
        campaign=Campaign(RUN/'CAMPAIGN_AUTH.json',RUN,directory/'STAGE_AUTHORITY.json');meter.campaign=campaign
        qual=read(runtime.cohort/'qualification.json')
        print(json.dumps({'phase':'begin','application':'dify','round':2,'candidate':'P2','native_questions':48}),flush=True)
        result=acquire(meter,CanonicalContracts(read(runtime.cohort/'contracts.json')),qual['task_ids'],phase='development',guard=guard)
        gate=gate_saved_acquisition(meter.run_dir,application_id='dify',cohort_id='development',prompt_id='P2',
            prompt_text_sha256=scope['prompt_text_sha256'],input_freeze_sha256=scope['input_freeze_sha256'],mode='development',
            task_ids=qual['task_ids'],contract_document=read(runtime.cohort/'contracts.json'),witnesses=qual['qualification_witnesses'],
            controls={s:qual['unaffected_controls'] for s in ('A_BAD','B_BAD')},bad_subsets=qual['qualification_subsets'])
        write_new(output/'ADMISSION_GATE.json',gate)
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        if meter is not None and not (meter.run_dir/'CLEANUP.json').exists():
            try:meter.cleanup()
            except Exception as cleanup:error['cleanup_error']=str(cleanup)
    finally:
        if campaign is not None:campaign.close()
    write_new(output/'DRIVER_COMPLETION.json',{'application_id':'dify','mode':'development','prompt_id':'P2',**scope,
        'execution_completed':error is None,'error':error,'result':result,'admission_passed':gate['passed'] if gate else None,
        'policy_efficacy_evaluated':False,'adaptive_development_round':2})
    print(json.dumps({'phase':'end','execution_completed':error is None,'admission_passed':gate['passed'] if gate else None,'error':error}),flush=True)
    if error:raise RuntimeError(str(error))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('declare','run'));args=parser.parse_args()
    declare() if args.mode=='declare' else run()

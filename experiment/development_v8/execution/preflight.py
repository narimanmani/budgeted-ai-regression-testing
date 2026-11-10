"""Pure selected-configuration and fresh-acquisition continuity checks for v8."""
from pathlib import Path
import hashlib
import json
import re

from experiment.development_v8.execution.runner import ROOT, StudyIncident, read, sha, utc, write_new
from experiment.development_v8.protocol.gates import gate_saved_acquisition, POLICY_SHA256
from experiment.validation_v7.guidance import policy

APPS = ('openwebui', 'dify')


def root_path(recorded):
    path=Path(recorded)
    path=(path if path.is_absolute() else ROOT/path).resolve()
    if not path.is_relative_to(ROOT):raise StudyIncident('Frozen path is outside this research workspace')
    return path


def frozen_map(document):
    values=document.get('files_sha256',{})
    if not isinstance(values,dict) or not values:raise StudyIncident('Nonempty exact frozen file map required')
    result={}
    for recorded,expected in values.items():
        path=root_path(recorded)
        if path in result or sha(path)!=expected:raise StudyIncident('Frozen source/input changed or duplicated: '+recorded)
        result[path]=expected
    return result


def validate_outer_freeze(path):
    path=Path(path).resolve();document=read(path)
    if (document.get('phase')!='EXTERNAL_V8'
            or document.get('original_guidance_freeze_sha256')!=sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json')
            or set(document.get('selected_prompt_by_application',{}))!=set(APPS)):
        raise StudyIncident('Current v8 validation freeze and selected configuration for both apps required')
    if sha(ROOT/'experiment/validation_v7/guidance/policy.py')!=POLICY_SHA256:
        raise StudyIncident('CG1 changed after its original freeze')
    mapping=frozen_map(document)
    dev_path=path.parent/'DEVELOPMENT_FREEZE.json'
    if document.get('development_freeze_sha256')!=sha(dev_path):
        raise StudyIncident('Validation freeze must bind the original prospective development freeze')
    development=read(dev_path);old=frozen_map(development)
    candidates=document.get('candidate_order_by_application',{})
    if set(candidates)!=set(APPS):raise StudyIncident('Every selected configuration needs its explicitly declared candidate order')
    authorized={app:{'P0','P1'} for app in APPS}
    for extension in document.get('additional_development_rounds',[]):
        app=extension.get('application_id');extra=extension.get('candidate_ids',[])
        if app not in APPS or len(extra)!=1 or len(set(extra))!=1:
            raise StudyIncident('Each adaptive development extension must declare one bounded candidate')
        declaration=root_path(extension.get('path',''))
        if (declaration not in mapping or mapping[declaration]!=extension.get('sha256')
                or sha(declaration)!=extension.get('sha256')):
            raise StudyIncident('Adaptive development declaration is not frozen in the validation closure')
        registered=read(declaration)
        if (registered.get('phase')!='EXTERNAL_V8'
                or registered.get('original_development_freeze_sha256')!=sha(dev_path)
                or registered.get('additional_candidate_order')!=extra
                or registered.get('additional_native_questions')!=48
                or registered.get('fresh_validation_answers_before_extension')!=0
                or registered.get('policy_outcomes_before_extension')!=0
                or registered.get('original_two_candidate_protocol_adherence_claimed') is not False
                or registered.get('original_protocol_data_prompts_judgments_and_results_modified') is not False):
            raise StudyIncident('Adaptive development provenance/stop/freshness disclosure is incomplete')
        stopped=Path(path).resolve().parent/'DEVELOPMENT_SELECTION.json'
        if registered.get('round1_closed_decision_sha256')!=sha(stopped):
            raise StudyIncident('Original failed development selection was not retained and closed')
        authorized[app].update(extra)
    for app in APPS:
        order=candidates[app]
        if (not isinstance(order,list) or order[:2]!=['P0','P1'] or len(order)!=len(set(order))
                or set(order)!=authorized[app]
                or any(not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,20}',value) for value in order)
                or document['selected_prompt_by_application'][app] not in order):
            raise StudyIncident('Selected prompt has an undeclared development candidate or ordering')
    for app in APPS:
        directory=ROOT/'experiment/development_v8/workloads/validation'/app
        for file in directory.rglob('*'):
            if file.is_file() and (file not in old or file not in mapping or old[file]!=mapping[file]):
                raise StudyIncident('Fresh validation bytes differ from the pre-development commitment')
    return document,mapping


def load_case(validation_freeze,app):
    if app not in APPS:raise StudyIncident('Unregistered application')
    freeze,mapping=validate_outer_freeze(validation_freeze)
    prompt=freeze['selected_prompt_by_application'][app]
    directory=ROOT/'experiment/development_v8/workloads/validation'/app
    input_path=Path(validation_freeze).resolve().parent/'input_freezes'/f'validation_{app}_{prompt}.json'
    input_document=read(input_path)
    if input_path not in mapping or input_document.get('cohort_id')!='validation' or input_document.get('prompt_id')!=prompt:
        raise StudyIncident('Selected fresh input sidecar is not bound by the outer validation freeze')
    input_mapping=frozen_map(input_document)
    names=('tasks.json','contracts.json','source_manifest.json','qualification.json')
    if any(directory/name not in input_mapping for name in names):
        raise StudyIncident('Actual fresh tasks/contracts/sources/witness frame are not frozen')
    qualification=read(directory/'qualification.json');task_ids=qualification['task_ids']
    contract_document=read(directory/'contracts.json')
    if (len(task_ids)!=8 or len(set(task_ids))!=8
            or set(task_ids)!={row['id'] for row in contract_document['contracts']}
            or len(contract_document['contracts'])!=8):
        raise StudyIncident('Exact fresh eight-task catalog required')
    if app=='openwebui':
        source=read(ROOT/'experiment/validation_v7/openwebui/SOURCE_MANIFEST.json')
        changed={state:policy.tokens(source['overrides'][state]['public_change_tokens']) for state in ('A_BAD','B_BAD')}
    else:
        source=read(ROOT/'experiment/validation_v7/dify/EFFECTIVE_SOURCE_TOKEN_AMENDMENT.json')
        changed={state:policy.tokens(['code:'+path for path in source['effective_source_tokens'][state]['all_actual_changed_production_paths']])
                 for state in ('A_BAD','B_BAD')}
    scope={'cohort_id':'validation','prompt_candidate_id':prompt,
           'prompt_text_sha256':input_document['prompt_text_sha256'],'input_freeze_sha256':sha(input_path)}
    bundle={'application_id':app,'scope':scope,
            'case_files_sha256':{str(file):mapping[file] for file in directory.rglob('*') if file.is_file()},
            'qualification':qualification,'changed_tokens_by_episode':{1:changed['A_BAD'],2:changed['A_BAD'],3:changed['B_BAD']}}
    return {**bundle,'cohort_bundle_sha256':policy.digest(bundle),'task_ids':task_ids,
            'cohort_dir':directory,'input_freeze_path':input_path,'contract_document':contract_document,
            'validation_freeze_sha256':sha(validation_freeze)}


def acquisition_directory(value):
    directory=Path(value).resolve()
    choices=[p for p in (directory,directory/'meter') if (p/'REFERENCE_COMPLETION.json').is_file()]
    if len(choices)!=1:raise StudyIncident('One explicit complete acquisition directory required')
    return choices[0]


def strict_acquisition_gate(case,value,mode,validation_freeze):
    directory=acquisition_directory(value);q=case['qualification'];scope=case['scope']
    gate=gate_saved_acquisition(directory,application_id=case['application_id'],
        cohort_id=scope['cohort_id'],prompt_id=scope['prompt_candidate_id'],
        prompt_text_sha256=scope['prompt_text_sha256'],input_freeze_sha256=scope['input_freeze_sha256'],
        mode=mode,task_ids=case['task_ids'],contract_document=case['contract_document'],
        witnesses=q['qualification_witnesses'],
        controls={state:q['unaffected_controls'] for state in ('A_BAD','B_BAD')},
        bad_subsets=q['qualification_subsets'])
    freeze_path=directory.parent/'ACQUISITION_SOURCE_FREEZE.json';frozen=read(freeze_path)
    if (frozen.get('root_freeze_sha256')!=sha(validation_freeze)
            or frozen.get('mode')!=mode or frozen.get('application_id')!=case['application_id']
            or any(frozen.get(key)!=value for key,value in scope.items())):
        raise StudyIncident('Acquisition source freeze belongs to another role/configuration/validation frame')
    captured={root_path(recorded):digest for recorded,digest in frozen.get('files_sha256',{}).items()}
    outer,mapping=validate_outer_freeze(validation_freeze)
    if any(captured.get(path)!=digest for path,digest in mapping.items()):
        raise StudyIncident('Native acquisition source freeze omitted or changed the prospective validation implementation/input closure')
    for name in ('tasks.json','contracts.json','source_manifest.json','qualification.json'):
        path=case['cohort_dir']/name
        if captured.get(path)!=sha(path):raise StudyIncident('Native acquisition did not bind the fresh case frame')
    original=directory.parent/'ADMISSION_GATE.json'
    if not original.is_file():raise StudyIncident('Original root acquisition gate is missing')
    previous=read(original)
    for field in ('application_id','cohort_id','prompt_id','mode','passed','outputs','healthy_primary_passes',
                  'violated_conditions','rechecked_raw_evidence','completion_sha256'):
        if gate[field]!=previous[field]:raise StudyIncident('Independently refreshed gate differs from the original gate')
    return {**gate,'acquisition_dir':str(directory),'cohort_bundle_sha256':case['cohort_bundle_sha256'],
            'acquisition_source_freeze_path':str(freeze_path),'acquisition_source_freeze_sha256':sha(freeze_path),
            'original_gate_path':str(original),'original_gate_sha256':sha(original)}


def build_preflight(validation_freeze,acquisitions,output):
    if set(acquisitions)!=set(APPS):raise StudyIncident('Both prospectively fixed apps required')
    cases={app:load_case(validation_freeze,app) for app in APPS}
    output=Path(output).resolve()
    if output.exists():raise FileExistsError('Preflight cannot overwrite previous evidence')
    output.mkdir(parents=True)
    applications={};all_requests=set()
    for app in APPS:
        if set(acquisitions[app])!={'qualification','reference'}:raise StudyIncident('Both fresh acquisition roles required')
        applications[app]={}
        for mode in ('qualification','reference'):
            gate=strict_acquisition_gate(cases[app],acquisitions[app][mode],mode,validation_freeze)
            if not gate['passed']:raise StudyIncident('Fresh qualification/reference gate failed; no main comparison')
            ids={row['request_id'] for row in gate['rechecked_raw_evidence']}
            if all_requests.intersection(ids):raise StudyIncident('Native outputs reused across acquisition roles')
            all_requests.update(ids)
            gate_path=output/f'{app}_{mode}_GATE.json';write_new(gate_path,gate)
            applications[app][mode]={'gate_path':str(gate_path),'gate_sha256':sha(gate_path)}
    result={'phase':'EXTERNAL_V8','created_at_utc':utc(),
            'validation_freeze_path':str(Path(validation_freeze).resolve()),
            'validation_freeze_sha256':sha(validation_freeze),'applications':applications,
            'both_apps_qualified_and_reference_complete_before_main':True,
            'distinct_native_acquisition_questions':len(all_requests),'new_native_or_model_queries':0,
            'freshness_scope':'New held-out workload instances in the same developed applications/fault families'}
    write_new(output/'PREFLIGHT_INDEX.json',result)
    return result


def refresh_preflight(index_path,validation_freeze):
    index=read(index_path)
    if (index.get('phase')!='EXTERNAL_V8' or index.get('validation_freeze_sha256')!=sha(validation_freeze)
            or set(index.get('applications',{}))!=set(APPS)
            or index.get('both_apps_qualified_and_reference_complete_before_main') is not True):
        raise StudyIncident('Both-app fresh preflight is not bound to the current validation freeze')
    requests=set()
    for app in APPS:
        case=load_case(validation_freeze,app)
        if set(index['applications'][app])!={'qualification','reference'}:
            raise StudyIncident('Fresh preflight lacks a complete acquisition role')
        for mode,item in index['applications'][app].items():
            path=Path(item['gate_path'])
            if sha(path)!=item['gate_sha256']:raise StudyIncident('Stored preflight gate changed')
            gate=read(path);refreshed=strict_acquisition_gate(case,gate['acquisition_dir'],mode,validation_freeze)
            if refreshed!=gate or not refreshed['passed']:raise StudyIncident('Fresh evidence/source-freeze continuity no longer reconciles')
            ids={row['request_id'] for row in gate['rechecked_raw_evidence']}
            if requests.intersection(ids):raise StudyIncident('A native question was reused in preflight')
            requests.update(ids)
    if len(requests)!=160 or index.get('distinct_native_acquisition_questions')!=160:
        raise StudyIncident('Complete 64 qualification plus96 independent reference questions required')
    return index

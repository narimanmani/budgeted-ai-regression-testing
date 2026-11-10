"""Synthetic native-receipt fixtures only; never starts a subject/provider."""
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import pytest

from experiment.development_v8.execution import factory, preflight
from experiment.development_v8.execution.runner import StudyIncident
from experiment.development_v8.protocol.gates import gate_saved_acquisition


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n' if not isinstance(value,str) else value,encoding='utf-8')
    return path


@pytest.fixture
def environment(tmp_path,monkeypatch):
    original=preflight.ROOT;policy=(original/'experiment/validation_v7/guidance/policy.py').read_bytes()
    root=tmp_path/'workspace';root.mkdir();run=root/'experiment/runs/v8-synthetic';run.mkdir(parents=True)
    monkeypatch.setattr(preflight,'ROOT',root);monkeypatch.setattr(factory,'ROOT',root)
    guide=write(root/'experiment/validation_v7/GUIDANCE_FREEZE.json',{'synthetic_guide_record':True})
    target=root/'experiment/validation_v7/guidance/policy.py';target.parent.mkdir(exist_ok=True);target.write_bytes(policy)
    changed={'effective_source_tokens':{state:{'all_actual_changed_production_paths':['api/'+state+'.py']}
                                      for state in ('A_BAD','B_BAD')}}
    write(root/'experiment/validation_v7/dify/EFFECTIVE_SOURCE_TOKEN_AMENDMENT.json',changed)
    write(root/'experiment/validation_v7/openwebui/SOURCE_MANIFEST.json',{
        'overrides':{state:{'public_change_tokens':['code:backend/loader.py']} for state in ('A_BAD','B_BAD')}})
    prompt='Fixed generic record lookup instruction';prompt_sha=hashlib.sha256(prompt.encode()).hexdigest()
    files={};cohorts={};inputs={}
    for app in ('openwebui','dify'):
        directory=root/'experiment/development_v8/workloads/validation'/app
        task_ids=[app+'-T'+str(i) for i in range(1,9)]
        qualification={'task_ids':task_ids,'qualification_witnesses':{'A_BAD':task_ids[0],'B_BAD':task_ids[2]},
            'unaffected_controls':task_ids[4:6],
            'qualification_subsets':{'A_BAD':task_ids[:2]+task_ids[4:6],'B_BAD':task_ids[2:4]+task_ids[4:6]}}
        write(directory/'tasks.json',{'tasks':[{'id':task,'question':'Read '+task,'data_version':'v1'} for task in task_ids]})
        write(directory/'contracts.json',{'contracts':[{'id':task,'data_version':'v1','accepted_values':['GOOD_'+task],
             'required_logical_source_id':task+'.txt','required_source_version':'v1'} for task in task_ids]})
        write(directory/'source_manifest.json',{'cohort_id':'validation','sources':[]})
        write(directory/'qualification.json',qualification)
        for task in task_ids:write(directory/'fixtures'/(task+'.txt'),'Record ['+'GOOD_'+task+']')
        for path in directory.rglob('*'):
            if path.is_file():files[str(path.relative_to(root))]=preflight.sha(path)
        cohorts[app]=directory
    dev=write(run/'DEVELOPMENT_FREEZE.json',{'files_sha256':files.copy()})
    auth=write(run/'CAMPAIGN_AUTH.json',{'provider_phase':'EXTERNAL_V8','campaign_run_dir':str(run),
        'provider_state_dir':str(run/'provider'),'guidance_freeze_sha256':preflight.sha(guide)})
    runtimeauth=write(run/'RUNTIME_AUTH.json',{'provider_phase':'EXTERNAL_V8','provider_state_dir':str(run/'provider'),
        'guidance_freeze_sha256':preflight.sha(guide),'run_root':str(run)})
    for app in ('openwebui','dify'):
        inputs[app]=write(run/'input_freezes'/f'validation_{app}_P0.json',{
            'cohort_id':'validation','prompt_id':'P0','prompt_text_sha256':prompt_sha,
            'files_sha256':{str(path.relative_to(root)):preflight.sha(path) for path in cohorts[app].rglob('*') if path.is_file()}})
        files[str(inputs[app].relative_to(root))]=preflight.sha(inputs[app])
    configs={};slots=[]
    for app,rep in (('openwebui',1),('dify',1),('openwebui',2),('dify',2)):
        slots.append({'application_id':app,'repetition':rep,'output_dir':str(run/f'main-{app}-r{rep}')})
        configs[app,rep]=write(run/'runtime_configs'/f'main_{app}_r{rep}.json',{
            'cohort_id':'validation','prompt_id':'P0','prompt_text':prompt,'cohort_dir':str(cohorts[app]),
            'input_freeze_file':str(inputs[app]),'input_freeze_sha256':preflight.sha(inputs[app]),
            'runtime_authorization_file':str(runtimeauth),'receipt_scope':f'main-{app}-r{rep}',
            'scope_id':'validation-P0','allow_new_dataset_scope':False})
        files[str(configs[app,rep].relative_to(root))]=preflight.sha(configs[app,rep])
    implementation=write(root/'experiment/development_v8/execution/synthetic_implementation.py','SYNTHETIC=True\n')
    files[str(implementation.relative_to(root))]=preflight.sha(implementation)
    outer=write(run/'VALIDATION_FREEZE.json',{'phase':'EXTERNAL_V8',
        'original_guidance_freeze_sha256':preflight.sha(guide),'development_freeze_sha256':preflight.sha(dev),
        'selected_prompt_by_application':{'openwebui':'P0','dify':'P0'},
        'candidate_order_by_application':{'openwebui':['P0','P1'],'dify':['P0','P1']},
        'additional_development_rounds':[],'files_sha256':files,'main_block_order':slots})
    scope={'cohort_id':'validation','prompt_candidate_id':'P0','prompt_text_sha256':prompt_sha,
           'input_freeze_sha256':preflight.sha(inputs['openwebui'])}
    tasks=preflight.read(cohorts['openwebui']/'qualification.json')['task_ids']
    stage=write(run/'MAIN_STAGE.json',{'phase':'EXTERNAL_V8','authorized':True,'campaign_auth_sha256':preflight.sha(auth),
        'validation_freeze_sha256':preflight.sha(outer),'input_freeze_sha256':preflight.sha(inputs['openwebui']),
        'native_query_cap':568,'allowed_metadata_phases':['profile','calibration','comparison'],
        'allowed_tasks':tasks,'allowed_states':['HEALTHY','A_BAD','B_BAD'],'allowed_scope':scope})
    budget=write(run/'MAIN_BUDGETS.json',{'validation_freeze_sha256':preflight.sha(outer),'block_order':slots})
    args=SimpleNamespace(app='openwebui',rep=1,auth=auth,stage=stage,runtimeauth=runtimeauth,
        input_freeze=inputs['openwebui'],runtime_config=configs['openwebui',1],validation_freeze=outer,
        preflight_index=run/'UNUSED_SYNTHETIC_INDEX.json',budgets=budget,output=run/'main-openwebui-r1',
        infra_stage=None,runtime_dir=None)
    impact=SimpleNamespace(required_source_files=lambda app:[],build_impact=lambda *a,**k:None)
    monkeypatch.setattr(factory,'required_implementation_files',lambda:[implementation])
    monkeypatch.setattr(factory,'importlib',SimpleNamespace(import_module=lambda name:impact))
    return SimpleNamespace(root=root,run=run,outer=outer,cohorts=cohorts,inputs=inputs,
        prompt_sha=prompt_sha,configs=configs,args=args,implementation=implementation)


def write_acquisition(env,app,mode):
    case=preflight.load_case(env.outer,app);q=case['qualification'];scope=case['scope']
    base=env.run/f'{mode}-{app}';directory=base/'meter';(directory/'raw').mkdir(parents=True)
    rows=[]
    for state in ('HEALTHY','A_BAD','B_BAD'):
        tasks=q['qualification_subsets'][state] if mode=='qualification' and state!='HEALTHY' else case['task_ids']
        for repeat in (1,2):
            for task in tasks:
                request=f'{app}-{mode}-{state}-{task}-{repeat}'
                meta={'application_id':app,'phase':mode,'request_id':request,'state_id':state,'task_id':task,**scope}
                passed=not(state!='HEALTHY' and task==q['qualification_witnesses'][state])
                native={**meta,'valid_native_response':True,'completed':True,'answer':'GOOD_'+task if passed else 'BAD'}
                receipt={'allocation_id':request,'dispatch_safe_to_continue':True,'native_query_units_reserved':1,
                    'provider_join':{'joined':True},'native_reservation':{'request_id':request,'metadata':meta}}
                raw={**meta,'native_output':native,'root_meter_receipt':receipt}
                path=write(directory/'raw'/(request+'.json'),raw)
                rows.append({**meta,'repetition':repeat,'receipt_path':str(path),'receipt_sha256':preflight.sha(path),
                             'reference_check':{'primary_pass':passed}})
    write(directory/'sealed/reference_outputs.jsonl',''.join(json.dumps(row)+'\n' for row in rows))
    write(directory/'REFERENCE_COMPLETION.json',{'phase':mode,'error':None,'outputs':len(rows),'planned_outputs':len(rows)})
    outer=preflight.read(env.outer)
    write(base/'ACQUISITION_SOURCE_FREEZE.json',{'root_freeze_sha256':preflight.sha(env.outer),
        'application_id':app,'mode':mode,**scope,'files_sha256':outer['files_sha256']})
    gate=gate_saved_acquisition(directory,application_id=app,cohort_id='validation',prompt_id='P0',
        prompt_text_sha256=scope['prompt_text_sha256'],input_freeze_sha256=scope['input_freeze_sha256'],
        mode=mode,task_ids=case['task_ids'],contract_document=case['contract_document'],
        witnesses=q['qualification_witnesses'],controls={s:q['unaffected_controls'] for s in ('A_BAD','B_BAD')},
        bad_subsets=q['qualification_subsets'])
    write(base/'ADMISSION_GATE.json',gate)
    return base


def test_complete_selected_fresh_case_registry(environment):
    case=preflight.load_case(environment.outer,'dify')
    assert len(case['task_ids'])==8 and case['scope']['cohort_id']=='validation'
    assert case['changed_tokens_by_episode'][1]!=case['changed_tokens_by_episode'][3]


def test_validation_bytes_cannot_be_changed_after_development_commitment(environment):
    file=environment.cohorts['dify']/'fixtures/dify-T1.txt';file.write_text('changed',encoding='utf-8')
    with pytest.raises(StudyIncident):preflight.load_case(environment.outer,'dify')


def test_undeclared_third_candidate_cannot_replace_closed_round1(environment):
    outer=preflight.read(environment.outer)
    outer['selected_prompt_by_application']['dify']='P2'
    outer['candidate_order_by_application']['dify'].append('P2');write(environment.outer,outer)
    with pytest.raises(StudyIncident):preflight.validate_outer_freeze(environment.outer)


def test_explicit_bounded_round2_authorization_does_not_rewrite_round1(environment):
    outer=preflight.read(environment.outer)
    closed=write(environment.run/'DEVELOPMENT_SELECTION.json',{'status':'STOP_ROUND1','selected_dify':None})
    declaration=write(environment.run/'development_round2/ROUND2_FREEZE.json',{
        'phase':'EXTERNAL_V8','original_development_freeze_sha256':outer['development_freeze_sha256'],
        'additional_candidate_order':['P2'],'additional_native_questions':48,
        'fresh_validation_answers_before_extension':0,'policy_outcomes_before_extension':0,
        'original_two_candidate_protocol_adherence_claimed':False,
        'original_protocol_data_prompts_judgments_and_results_modified':False,
        'round1_closed_decision_sha256':preflight.sha(closed)})
    outer['files_sha256'][str(declaration.relative_to(environment.root))]=preflight.sha(declaration)
    outer['additional_development_rounds']=[{'path':str(declaration),'sha256':preflight.sha(declaration),
                                          'application_id':'dify','candidate_ids':['P2']}]
    outer['selected_prompt_by_application']['dify']='P2'
    outer['candidate_order_by_application']['dify'].append('P2');write(environment.outer,outer)
    checked,mapping=preflight.validate_outer_freeze(environment.outer)
    assert checked['selected_prompt_by_application']['dify']=='P2' and declaration in mapping
    assert preflight.read(closed)['status']=='STOP_ROUND1'


def test_all160_fresh_native_receipts_and_source_freezes_refresh(environment):
    acquisitions={app:{mode:write_acquisition(environment,app,mode) for mode in ('qualification','reference')}
                  for app in ('openwebui','dify')}
    preflight.build_preflight(environment.outer,acquisitions,environment.run/'preflight')
    index=preflight.refresh_preflight(environment.run/'preflight/PREFLIGHT_INDEX.json',environment.outer)
    assert index['distinct_native_acquisition_questions']==160


def test_changed_acquisition_source_freeze_cannot_enter_main(environment):
    acquisitions={app:{mode:write_acquisition(environment,app,mode) for mode in ('qualification','reference')}
                  for app in ('openwebui','dify')}
    preflight.build_preflight(environment.outer,acquisitions,environment.run/'preflight')
    file=acquisitions['dify']['reference']/'ACQUISITION_SOURCE_FREEZE.json'
    value=preflight.read(file);value['root_freeze_sha256']='0'*64;write(file,value)
    with pytest.raises(StudyIncident):preflight.refresh_preflight(environment.run/'preflight/PREFLIGHT_INDEX.json',environment.outer)


def test_valid_argument_validation_is_pure_and_creates_no_native_state(environment,monkeypatch):
    monkeypatch.setattr(factory,'refresh_preflight',lambda *a:True)
    ready=factory.validate_block_arguments(environment.args)
    assert ready['case']['scope']['cohort_id']=='validation' and not environment.args.output.exists()


@pytest.mark.parametrize('field,value',[('native_query_cap',672),('validation_freeze_sha256','0'*64),
                                     ('input_freeze_sha256','1'*64)])
def test_wrong_main_authority_rejected_before_output_or_native_work(environment,monkeypatch,field,value):
    monkeypatch.setattr(factory,'refresh_preflight',lambda *a:True)
    stage=preflight.read(environment.args.stage);stage[field]=value;write(environment.args.stage,stage)
    with pytest.raises(StudyIncident):factory.run_block(environment.args)
    assert not environment.args.output.exists()


def test_wrong_reserved_prompt_scope_rejected(environment,monkeypatch):
    monkeypatch.setattr(factory,'refresh_preflight',lambda *a:True)
    stage=preflight.read(environment.args.stage);stage['allowed_scope']['prompt_candidate_id']='P1';write(environment.args.stage,stage)
    with pytest.raises(StudyIncident):factory.validate_block_arguments(environment.args)


def test_full_main_budget_order_cannot_be_replaced_by_subset(environment,monkeypatch):
    monkeypatch.setattr(factory,'refresh_preflight',lambda *a:True)
    budget=preflight.read(environment.args.budgets);budget['block_order']=budget['block_order'][:1];write(environment.args.budgets,budget)
    with pytest.raises(StudyIncident):factory.validate_block_arguments(environment.args)


def test_missing_main_implementation_freeze_is_rejected(environment,monkeypatch):
    monkeypatch.setattr(factory,'refresh_preflight',lambda *a:True)
    outer=preflight.read(environment.outer)
    outer['files_sha256'].pop(str(environment.implementation.relative_to(environment.root)))
    write(environment.outer,outer)
    stage=preflight.read(environment.args.stage);stage['validation_freeze_sha256']=preflight.sha(environment.outer);write(environment.args.stage,stage)
    budget=preflight.read(environment.args.budgets);budget['validation_freeze_sha256']=preflight.sha(environment.outer);write(environment.args.budgets,budget)
    with pytest.raises(StudyIncident):factory.validate_block_arguments(environment.args)

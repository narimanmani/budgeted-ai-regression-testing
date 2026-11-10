"""One-shot pre-answer development declaration and four bounded stage authorities."""
from pathlib import Path
from datetime import datetime, timezone
from experiment.development_v8.control import read, sha, write_new
from experiment.development_v8.protocol.gates import budget_projection

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'experiment/runs/development_v8_20261101'

def relative(path):return str(path.relative_to(ROOT)).replace('\\','/')

def main():
    counter=read(RUN/'provider/COUNTER.json')
    if counter['chat_requests_reserved'] or counter['embedding_requests_started']:
        raise RuntimeError('Development must be declared before any new native/provider boundary')
    authority=read(HERE/'workloads/WORKLOAD_AUTHORITY_AUDIT.json')
    runtime=read(HERE/'RUNTIME_OFFLINE_VALIDATION.json')
    if authority['passed'] is not True or runtime['passed'] is not True:raise RuntimeError('Offline admission proof required')
    paths=set()
    for record in (read(HERE/'workloads/WORKLOAD_FILES.json'),authority,runtime):
        for key in ('files_sha256','inherited_read_only_files_sha256'):
            for name,expected in record.get(key,{}).items():
                p=Path(name);p=p if p.is_absolute() else ROOT/p
                if sha(p)!=expected:raise RuntimeError('Reviewed bytes changed: '+name)
                paths.add(p.resolve())
    paths.update((HERE/name).resolve() for name in ('acquisition.py','test_acquisition.py','control.py',
        'provider_bridge.py','initialize.py','freeze_development.py','run_acquisition.py',
        'ACCOUNTING_DERIVATION.json','RUNTIME_OFFLINE_VALIDATION.json',
        'INDEPENDENT_PREDEV_AUDIT.json','PREDEV_OFFLINE_VALIDATION.json'))
    paths.update((HERE/'protocol'/name).resolve() for name in ('PROTOCOL_DRAFT.json','README.md','gates.py','test_gates.py'))
    paths.update((HERE/'workloads'/name).resolve() for name in ('WORKLOAD_FILES.json','WORKLOAD_AUTHORITY_AUDIT.json'))
    mapping={relative(p):sha(p) for p in sorted(paths)}
    prompts=read(HERE/'workloads/prompts.json')['candidates']
    if [p['id'] for p in prompts]!=['P0','P1']:raise RuntimeError('Fixed two-candidate order differs')
    auth=read(RUN/'CAMPAIGN_AUTH.json')
    for app in ('openwebui','dify'):
        cohort=HERE/'workloads/development'/app
        tasks=read(cohort/'tasks.json')['tasks']
        for prompt in prompts:
            prompt_id=prompt['id'];prompt_sha=__import__('hashlib').sha256(prompt['prompt_text'].encode()).hexdigest()
            input_path=RUN/'input_freezes'/f'development_{app}_{prompt_id}.json'
            write_new(input_path,{'cohort_id':'development','prompt_id':prompt_id,'prompt_text_sha256':prompt_sha,
                'files_sha256':mapping,'actual_development_or_validation_outputs_before_freeze':0})
            stage_path=RUN/'stage_authorities'/f'development_{app}_{prompt_id}.json'
            write_new(stage_path,{'phase':'EXTERNAL_V8','stage_id':f'development_{app}_{prompt_id}',
                'authorized':True,'campaign_auth_sha256':sha(RUN/'CAMPAIGN_AUTH.json'),
                'expires_at_epoch':auth['expires_at_epoch'],'allowed_states':['HEALTHY','A_BAD','B_BAD'],
                'allowed_tasks':[row['id'] for row in tasks],'allowed_metadata_phases':['development'],
                'native_query_cap':48,'cohort_id':'development','prompt_id':prompt_id,
                'prompt_text_sha256':prompt_sha,'input_freeze_sha256':sha(input_path)})
            config_path=RUN/'runtime_configs'/f'development_{app}_{prompt_id}.json'
            write_new(config_path,{'allow_native':True,'runtime_authorization_file':str(RUN/'RUNTIME_AUTH.json'),
                'cohort_dir':str(cohort),'cohort_id':'development','prompt_id':prompt_id,'prompt_text':prompt['prompt_text'],
                'input_freeze_file':str(input_path),'input_freeze_sha256':sha(input_path),
                'receipt_scope':f'development-{prompt_id}','scope_id':f'development-{prompt_id}',
                'allow_new_dataset_scope':prompt_id=='P1','rag_top_k':8 if app=='openwebui' else 20})
            paths.update((input_path,stage_path,config_path))
    write_new(RUN/'DEVELOPMENT_FREEZE.json',{
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'phase':'EXTERNAL_V8','formal_registration':False,
        'status':'DEVELOPMENT_AND_FRESH_WORKLOAD_BYTES_FROZEN_BEFORE_ANSWERS',
        'prior_qualification_exposure_acknowledged':'V7 retained; fresh workload instances on the same native apps/fault families',
        'original_guidance_freeze_sha256':sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'),
        'development_queries_before_freeze':0,'validation_queries_before_freeze':0,
        'candidate_order':['P0','P1'],'execute_both_candidates_fully':True,
        'selection_rule':'First eligible candidate in fixed order; stop if neither eligible; no policy results as inputs',
        'prospective_physical_query_projection':budget_projection(),
        'files_sha256':{relative(p):sha(p) for p in sorted(paths)}})
    print('Frozen four development frames and separate fresh validation bytes; zero new answers observed.')

if __name__=='__main__':main()

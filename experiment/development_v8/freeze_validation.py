"""Lock selected native configurations, fresh workload, main code and budgets."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import math
from experiment.development_v8.control import read, sha, write_new
from experiment.development_v8.execution.impact import required_source_files
from experiment.development_v8.execution.factory import required_implementation_files

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'experiment/runs/development_v8_20261101'
ORDER=(('openwebui',1),('dify',1),('openwebui',2),('dify',2))
def relative(p):return str(p.resolve().relative_to(ROOT)).replace('\\','/')

def main():
    selection=read(RUN/'DEVELOPMENT_FINAL_SELECTION.json')
    if selection['status']!='READY_TO_FREEZE_FRESH_VALIDATION':raise RuntimeError('Development eligibility prerequisite failed')
    old=read(RUN/'DEVELOPMENT_FREEZE.json');extension=read(RUN/'development_round2/ROUND2_FREEZE.json')
    paths=set()
    for frozen in (old,extension):
        for name,expected in frozen['files_sha256'].items():
            path=ROOT/name
            if sha(path)!=expected:raise RuntimeError('Precommitted code/data changed: '+name)
            paths.add(path.resolve())
    ledger=[json.loads(s) for s in (RUN/'native_reservations.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    if any(row['metadata']['phase'] not in ('development','setup_probe') for row in ledger):
        raise RuntimeError('Freeze must precede all fresh validation answers/policy decisions')
    ready=read(HERE/'execution/MAIN_SOFTWARE_READY.json')
    if (ready.get('status')!='MAIN_IMPLEMENTATION_READY_BEFORE_FRESH_VALIDATION_ANSWERS'
        or ready.get('software_tests_passed',0)<55):raise RuntimeError('Complete main software checks required before fresh validation')
    for name,expected in ready['files_sha256'].items():
        path=Path(name);path=path if path.is_absolute() else ROOT/path
        if sha(path)!=expected:raise RuntimeError('Tested main implementation changed')
        paths.add(path.resolve())
    for directory in (HERE/'execution',HERE/'audits'):
        paths.update(p.resolve() for p in directory.glob('*.py'))
        paths.update(p.resolve() for p in directory.glob('*.json'))
        paths.update(p.resolve() for p in directory.glob('*.md'))
    paths.update(p.resolve() for p in HERE.glob('*.py'))
    paths.update((HERE/name).resolve() for name in ('FRESH_DRIVER_DERIVATION.json','INDEPENDENT_PREDEV_AUDIT.json'))
    paths.update((RUN/name).resolve() for name in ('DEVELOPMENT_FREEZE.json','DEVELOPMENT_SELECTION.json',
        'DEVELOPMENT_FINAL_SELECTION.json','development_round2/ROUND2_FREEZE.json','development_round2/P2_PROMPT.json'))
    for app in ('openwebui','dify'):paths.update(Path(p).resolve() for p in required_source_files(app))
    paths.update(Path(p).resolve() for p in required_implementation_files())
    for name in ('runner.py','evaluate.py','source_channels.py'):
        paths.add(ROOT/'experiment/validation_v7/execution'/name)
    paths.update(ROOT/'experiment/native_v3/common'/name for name in ('contracts.py','reference.py'))
    # Actual old development latency informs feasibility, never candidate choice.
    old_latencies=[]
    for app,prompt in selection['selected_prompt_by_application'].items():
        folder=RUN/f'development-{app}-{prompt}'
        for line in (folder/'meter/query_index.jsonl').read_text(encoding='utf-8-sig').splitlines():
            row=json.loads(line)
            if row['phase']=='development' and row['state_id']=='HEALTHY':
                native=read(Path(row['receipt_path']));old_latencies.append(native['elapsed_seconds'])
        for name in ('ADMISSION_GATE.json','DRIVER_COMPLETION.json'):
            paths.add(folder/name)
        paths.add(RUN/'audits'/f'INDEPENDENT_DEVELOPMENT_{app.upper()}_{prompt}.json')
    projected_remaining=math.ceil(1.5*2432*max(old_latencies))
    counter=read(RUN/'provider/COUNTER.json');auth=read(RUN/'CAMPAIGN_AUTH.json')
    gpu_room=min(auth['phase_gpu_cap_seconds']-counter['gpu_allocation_seconds_accounted'],
        auth['shared_gpu_cap_seconds']-auth['prior_shared_gpu_seconds']-counter['gpu_allocation_seconds_accounted'])
    if 2432>auth['native_query_cap']-len(ledger) or projected_remaining>gpu_room:
        raise RuntimeError('Complete fresh qualification/reference/main continuation does not fit actual remaining resources')
    mapping={relative(p):sha(p) for p in sorted(paths)}
    prompts={p['id']:p for p in read(HERE/'workloads/prompts.json')['candidates']}
    prompts['P2']=read(RUN/'development_round2/P2_PROMPT.json')
    scopes={};config_files={};stage_specs=[]
    for app,prompt_id in selection['selected_prompt_by_application'].items():
        prompt=prompts[prompt_id];prompt_sha=hashlib.sha256(prompt['prompt_text'].encode()).hexdigest()
        cohort=HERE/'workloads/validation'/app
        input_path=RUN/'input_freezes'/f'validation_{app}_{prompt_id}.json'
        write_new(input_path,{'cohort_id':'validation','prompt_id':prompt_id,'prompt_text_sha256':prompt_sha,
            'files_sha256':mapping,'fresh_native_answer_outputs_before_freeze':0})
        scopes[app]={'cohort_id':'validation','prompt_candidate_id':prompt_id,
            'prompt_text_sha256':prompt_sha,'input_freeze_sha256':sha(input_path)}
        paths.add(input_path)
        modes=[('qualification',200),('reference',201),('main-r1',1),('main-r2',2)]
        for mode,repetition in modes:
            is_main=mode.startswith('main')
            config_name=f'main_{app}_r{repetition}.json' if is_main else f'{mode}_{app}_{prompt_id}.json'
            config_path=RUN/'runtime_configs'/config_name
            receipt_scope=f'main-{app}-r{repetition}' if is_main else f'{mode}-{app}-{prompt_id}'
            write_new(config_path,{'allow_native':True,'runtime_authorization_file':str(RUN/'RUNTIME_AUTH.json'),
                'cohort_dir':str(cohort),'cohort_id':'validation','prompt_id':prompt_id,'prompt_text':prompt['prompt_text'],
                'input_freeze_file':str(input_path),'input_freeze_sha256':sha(input_path),
                'receipt_scope':receipt_scope,'scope_id':'validation-'+prompt_id,
                'allow_new_dataset_scope':mode=='qualification','rag_top_k':8 if app=='openwebui' else 20})
            paths.add(config_path);config_files[config_name]=relative(config_path)
            stage_specs.append((app,prompt_id,mode,repetition,input_path))
    order=[{'application_id':app,'repetition':rep,'output_dir':str(RUN/f'main-{app}-r{rep}')} for app,rep in ORDER]
    outer=RUN/'VALIDATION_FREEZE.json'
    write_new(outer,{
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'phase':'EXTERNAL_V8','formal_registration':False,
        'status':'FRESH_WORKLOAD_AND_FULL_COMPARISON_LOCKED_BEFORE_NATIVE_VALIDATION_ANSWERS',
        'original_guidance_freeze_sha256':sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'),
        'development_freeze_sha256':sha(RUN/'DEVELOPMENT_FREEZE.json'),
        'development_final_selection_sha256':sha(RUN/'DEVELOPMENT_FINAL_SELECTION.json'),
        'selected_prompt_by_application':selection['selected_prompt_by_application'],
        'candidate_order_by_application':{'openwebui':['P0','P1'],'dify':['P0','P1','P2']},
        'additional_development_rounds':[{'path':str(RUN/'development_round2/ROUND2_FREEZE.json'),
            'sha256':sha(RUN/'development_round2/ROUND2_FREEZE.json'),'application_id':'dify','candidate_ids':['P2']}],
        'adaptive_development_extension_disclosed':True,'original_round1_success_claimed':False,
        'freshness_scope':'Same-format held-out workload instances on previously developed applications and known historical fault families',
        'validation_answers_before_freeze':0,'policy_decisions_before_freeze':0,
        'allowed_scope_by_application':scopes,'runtime_config_files':config_files,
        'main_block_order':order,'main_native_query_ceiling':2272,'main_native_ceiling_per_block':568,
        'prospective_main_generation_admission_ceiling_seconds':24000,'per_query_full_lifetime_cushion_seconds':600,
        'full_remaining_scientific_native_ceiling_before_validation':2432,
        'paid_development_healthy_max_native_wall_seconds':max(old_latencies),
        'prospective_remaining_generation_projection_seconds':projected_remaining,
        'projection_formula':'ceil(1.5 * 2432 * max(selected development HEALTHY native query wall seconds))',
        'actual_native_units_reserved_before_validation':len(ledger),
        'actual_generation_allocation_seconds_before_validation':counter['gpu_allocation_seconds_accounted'],
        'main_budget_master_baselines':'Sealed from actual cumulative counters after both reference banks, before first policy/profile/warm-history execution; fixed outputs/order/native ceilings remain unchanged',
        'files_sha256':{relative(p):sha(p) for p in sorted(paths)}})
    # Stage sidecars bind the outer freeze after it exists; excluding sidecars
    # from that outer file map avoids a circular self-hash dependency.
    for app,prompt_id,mode,rep,input_path in stage_specs:
        is_main=mode.startswith('main');role='main' if is_main else mode
        stage_name=f'main_{app}_r{rep}' if is_main else f'{mode}_{app}_{prompt_id}'
        tasks=read(HERE/'workloads/validation'/app/'tasks.json')['tasks']
        write_new(RUN/'stage_authorities'/(stage_name+'.json'),{
            'phase':'EXTERNAL_V8','stage_id':stage_name,'authorized':True,
            'campaign_auth_sha256':sha(RUN/'CAMPAIGN_AUTH.json'),'expires_at_epoch':auth['expires_at_epoch'],
            'allowed_states':['HEALTHY','A_BAD','B_BAD'],'allowed_tasks':[t['id'] for t in tasks],
            'allowed_metadata_phases':['profile','calibration','comparison'] if is_main else [role],
            'native_query_cap':568 if is_main else (32 if role=='qualification' else 48),
            'validation_freeze_sha256':sha(outer),'input_freeze_sha256':sha(input_path),
            'allowed_scope':scopes[app]})
    print(json.dumps({'validation_frozen':True,'selected':selection['selected_prompt_by_application'],
        'complete_remaining_native_ceiling':2432,'remaining_generation_projection_seconds':projected_remaining}))

if __name__=='__main__':main()

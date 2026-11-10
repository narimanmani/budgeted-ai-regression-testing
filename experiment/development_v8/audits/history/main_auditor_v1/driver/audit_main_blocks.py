"""Read-only native/source/model/cost audit of one fully completed main block.

Incomplete blocks are rejected before raw answers are opened. This module never
dispatches applications or fits a policy, and it does not alter the frozen
retention/utility evaluation. Individual performance totals are left to the
prospectively frozen full-frame analysis.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import json

from experiment.development_v8.audits.audit_acquisition import (
    read, rows, sha, need, choose_provider_events, join_check, model_check, audit_sources,
)
from experiment.development_v8.audits.audit_native_dify import native_context
from experiment.development_v8.execution import runner, evaluate, impact
from experiment.development_v8.execution.analysis import audit_raw_role, audit_block_physical
from experiment.validation_v7.execution.source_channels import CanonicalContracts
from experiment.validation_v7.guidance import policy

ROOT=Path(__file__).resolve().parents[3]
POLICY_SHA256='f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989'
SCOPE=('cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256')

def complete_frame(completion,plan):
    need(completion.get('error') is None and completion.get('completed_trajectories')==20
        and completion.get('planned_trajectories')==20,'Completed twenty-trajectory block required before opening answers')
    identifiers={row['trajectory_id'] for row in plan}
    need(len(plan)==len(identifiers)==20,'Distinct frozen twenty-trajectory plan required')
    closure=completion.get('logical_episode_closures',{})
    need(set(closure)=={'1','2','3'} and all(len(values)==20 and set(values)==identifiers for values in closure.values()),
        'All twenty trajectories must close each of the three logical episodes')
    need(0<=completion['physical_usage']['native_query_units']<=568,'Physical block exceeds its568-query ceiling')
    return identifiers

def event_barrier(events,identifiers):
    releases=[(i,row) for i,row in enumerate(events) if row['kind']=='old_feature_block_released']
    need([row['state_id'] for _,row in releases]==['HEALTHY','A_BAD'],'Exactly one paid H and one paid A old-profile release required')
    a_index,a=releases[1]
    closed=[row for row in events[:a_index] if row['kind']=='episode_closed' and row['episode_index']==1]
    need(len(closed)==20 and {row['trajectory_id'] for row in closed}==identifiers,'A old-profile release precedes complete episode1 barrier')
    need(set(a['closed_episode1'])==identifiers,'A release proof omits episode1 closures')
    return {row['state_id']:row for _,row in releases},max(datetime.fromisoformat(row['at_utc']) for row in closed)

def profile_frame(raw,task_ids):
    profiles=[row for row in raw if row['phase']=='profile']
    counts=Counter((row['state_id'],row['task_id']) for row in profiles)
    expected={(state,task) for state in ('HEALTHY','A_BAD') for task in task_ids}
    need(len(task_ids)==8 and len(profiles)==48 and set(counts)==expected and all(n==3 for n in counts.values()),
        'Each block requires two paid24-query OLD profiles with three observations per task')
    return profiles

def common_features(results):
    groups=defaultdict(list)
    for result in results:
        need(len(result['decisions'])==3,'Three predecision records per trajectory required')
        for decision in result['decisions']:
            groups[decision['episode_index']].append((decision['feature_receipt_sha256'],decision['impact_receipt']['receipt_sha256']))
    need(set(groups)=={1,2,3} and all(len(values)==20 and len(set(values))==1 for values in groups.values()),
        'Matched strategies did not receive the same immutable paid OLD features/impact evidence')
    return {str(episode):values[0] for episode,values in groups.items()}

def verify_file_map(mapping,root=ROOT):
    checked=0
    for recorded,expected in mapping.items():
        path=Path(recorded);path=(path if path.is_absolute() else Path(root)/path).resolve()
        need(sha(path)==expected,'Frozen source/input changed: '+str(recorded));checked+=1
    return checked

def audit(run,block,reference,config_path,validation_freeze):
    run=Path(run).resolve();outer_dir=Path(block).resolve();directory=outer_dir/'block'
    completion=read(directory/'BLOCK_COMPLETION.json')
    # Reject a partial/failed acquisition before loading plan, raw answers or pairs.
    need(completion.get('error') is None and completion.get('completed_trajectories')==20
        and completion.get('planned_trajectories')==20,'Incomplete block; raw answers are not opened by this auditor')
    execution=read(directory/'BLOCK_EXECUTION_RESERVATION.json');identifiers=complete_frame(completion,execution['plan'])
    driver=read(outer_dir/'DRIVER_COMPLETION.json')
    need(driver.get('success') is True and driver.get('error') is None and driver['result']==completion,'Main driver closure differs from complete native block')
    application=completion['application_id'];repetition=completion['repetition']
    need(execution['plan']==runner.trajectory_plan(application,repetition),'Native strategy order differs from the fixed plan/mirrored repetition')
    config=read(config_path);cohort=Path(config['cohort_dir']);outer=read(validation_freeze);freeze=read(outer_dir/'MAIN_SOURCE_FREEZE.json')
    need(freeze['validation_freeze_sha256']==sha(validation_freeze),'Main validation-freeze binding changed')
    need(outer['validation_answers_before_freeze']==0 and outer['policy_decisions_before_freeze']==0,'Fresh validation freeze was not prospective')
    need(sha(ROOT/'experiment/validation_v7/guidance/policy.py')==POLICY_SHA256,'Original CG1 policy changed')
    guide=read(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json')
    guide_files=verify_file_map(guide['frozen_files_sha256']);outer_files=verify_file_map(outer['files_sha256'])
    main_files=verify_file_map(freeze['files_sha256'])
    scope=outer['allowed_scope_by_application'][application]
    need({key:freeze[key] for key in SCOPE}==scope and config['cohort_id']=='validation'
        and config['prompt_id']==scope['prompt_candidate_id'],'Native main scope differs from locked validation selection')
    need(str(Path(config_path).resolve()) in freeze['files_sha256'],'Caller configuration is outside the exact main source closure')
    need(cohort.resolve()==ROOT/'experiment/development_v8/workloads/validation'/application,'Caller cohort is not the frozen held-out workload')
    need(Path(reference).resolve()==run/f'reference-{application}-{scope["prompt_candidate_id"]}',
        'Caller reference bank differs from the fixed selected application bank')
    need(freeze['native_query_ceiling']==568 and freeze['development_outputs_used_as_history'] is False,'Main native budget/history source declaration differs')
    physical=audit_block_physical(directory,completion);meter=Path(physical['meter_dir'])
    paths=sorted((meter/'raw').glob('*.json'));raw=[read(path) for path in paths]
    need(len(paths)==len(raw)==completion['physical_usage']['native_query_units'],'Physical native query count differs')
    raw_map={row['request_id']:row for row in raw};need(len(raw_map)==len(raw),'Duplicated physical main request')
    paths_map={row['request_id']:path for row,path in zip(raw,paths,strict=True)}
    tasks=[row['id'] for row in read(cohort/'tasks.json')['tasks']]
    source_rows={row['logical_id']:row for row in read(cohort/'source_manifest.json')['sources']}
    profiles=profile_frame(raw,tasks)
    need(sum(row['phase']=='calibration' for row in raw)==160,'Ten warm trajectories must each physically acquire sixteen native history queries')
    need(sum(row['phase']=='comparison' for row in raw)<=360,'Paired comparison budget exceeded')
    setup_paths=[meter/'SETUP.json',*sorted((meter/'setup_steps').glob('*.json'))]
    setup=[read(path) for path in setup_paths]
    receipts=[row['root_meter_receipt'] for row in [*setup,*raw]]
    wanted=[ident for receipt in receipts for ident in receipt['provider_join']['provider_request_ids']]
    need(len(wanted)==len(set(wanted)),'A provider boundary is counted under multiple main operations')
    events=choose_provider_events(run/'provider/requests.jsonl',set(wanted))
    operation_index={row['allocation_id']:row for row in rows(run/'operation_index.jsonl')}
    ledger={row['request_id']:row for row in rows(run/'native_reservations.jsonl')}
    for receipt in receipts:
        entry=operation_index[receipt['allocation_id']];path=Path(receipt['receipt_path'])
        need(Path(entry['path']).resolve()==path.resolve() and sha(path)==entry['sha256'] and read(path)==receipt,'Sealed root main operation differs')
        chat,embedding=join_check(receipt,events)
        if receipt['native_query_units_reserved']==0:need(not chat,'Common metadata setup caused generation')
    backend_sha=read(run/'CAMPAIGN_AUTH.json')['backend_receipt_sha256']
    bindings={};source_proofs={};lengths=[];output_lengths=[];conversations=[];query_primary=[]
    contracts=CanonicalContracts(read(cohort/'contracts.json'))
    for row in raw:
        ident=row['request_id'];native=row['native_output'];state=row['state_id'];receipt=row['root_meter_receipt']
        audit_raw_role(row,application=application,phase=row['phase'])
        need({key:row[key] for key in SCOPE}==scope,'A main query uses development or another native configuration')
        need(receipt['native_reservation']==ledger[ident],'Actual main query lacks its exact prior ledger reservation')
        original=read(native['receipt_path']);need(sha(native['receipt_path'])==native['receipt_sha256'],'Original native main receipt changed')
        need(all(native[key]==value for key,value in original.items()),'Native response changed in root wrapper')
        if state not in bindings:
            bindings[state]=native['source_bindings'];source_proofs[state]=audit_sources(application,state,bindings[state],source_rows)
            model=impact._source_model(application,state)
            need(all(impact._binding_valid(binding,application,state,model) for binding in bindings[state]),'Full native source/dependency proof differs')
        else:need(native['source_bindings']==bindings[state],'Native indexed source binding changed during a block')
        chat,embedding=join_check(receipt,events);need(len(chat)==1,'Each main native query must generate exactly once')
        usage=model_check(chat[0],backend_sha);native_context(application,chat[0],native)
        lengths.append(usage['prompt_tokens']);output_lengths.append(usage['completion_tokens'])
        config_receipt=Path(native['native_configuration_receipt_path'])
        need(sha(config_receipt)==native['native_configuration_receipt_sha256'],'Actual native configuration receipt changed')
        actual=read(config_receipt)
        if application=='openwebui':
            need(actual['rag']['TOP_K']==8 and actual['rag']['RAG_TEMPLATE']==(config['prompt_text']+'\n<context>\n{{CONTEXT}}\n</context>').replace('\n',' '),'Actual OpenWebUI main prompt/retrieval configuration differs')
        else:
            need(actual['app_configuration_readback']['model_config']['pre_prompt']==config['prompt_text'],'Actual Dify main prompt differs')
            conversations.append(native['native_conversation_id'])
        checked=contracts.check(row['task_id'],native,bindings=native['source_bindings'],state=state,reference=True)
        query_primary.append(checked)
    need(set(bindings)=={'HEALTHY','A_BAD','B_BAD'} and len({proof['workspace_id'] for proof in source_proofs.values()})==3,'All three separate native source states required')
    if application=='dify':need(len(set(conversations))==len(raw),'Native conversation history reused between main calls')
    event_rows=rows(directory/'events.jsonl');release,latest_e1=event_barrier(event_rows,identifiers)
    decisions={(row['trajectory_id'],row['episode_index']):row for row in event_rows if row['kind']=='decision_recorded'}
    need(len(decisions)==60,'Every policy must have three distinct predispatch decisions')
    for row in raw:
        if row['phase']=='comparison':
            recorded=decisions[row['trajectory_id'],row['episode_index']]
            need(datetime.fromisoformat(recorded['at_utc'])<=datetime.fromisoformat(row['root_meter_receipt']['native_reservation']['reserved_at_utc']),
                'A policy decision was recorded after its selected native query reservation')
    for row in profiles:
        if row['state_id']=='A_BAD':need(datetime.fromisoformat(row['root_meter_receipt']['native_reservation']['reserved_at_utc'])>=latest_e1,'Paid A native profile was acquired before all episode1 trajectories closed')
    features={state:read(directory/'features'/(state+'.json')) for state in ('HEALTHY','A_BAD')}
    for state,feature in features.items():
        values=[row for row in profiles if row['state_id']==state]
        expected=policy.paired_cost_profile({task:[row['elapsed_seconds'] for row in values if row['task_id']==task] for task in tasks})
        need(feature['pair_cost_seconds']==expected and feature['actual_shared_physical_usage']==runner.usage(values),'Shared cost profile differs from its paid three-pass native observations')
        projections=[]
        for row in values:
            path=paths_map[row['request_id']]
            projections.append(runner.profile_feature({**row,'receipt_path':str(path.resolve()),'receipt_sha256':sha(path)}))
        by_id={row['request_id']:row for row in projections}
        need(len(feature['observations'])==24 and all(by_id.get(row['request_id'])==row for row in feature['observations']),'Profile projection includes unpaid/foreign/changed native data')
        need(feature['release_episode']==(1 if state=='HEALTHY' else 2),'Future old-state feature release is invalid')
    result_paths=sorted((directory/'trajectories').glob('*/TRAJECTORY_RESULT.json'))
    results=[read(path) for path in result_paths]
    need(len(results)==20 and {row['trajectory_id'] for row in results}==identifiers,'Complete unique trajectory exports differ from original plan')
    shared=common_features(results)
    truth,cells=evaluate.reference_truth(Path(reference)/'meter',contracts)
    rechecked=[];own_ids=set();warm=0
    for path,result in zip(result_paths,results,strict=True):
        need(result['application_id']==application and result['repetition']==repetition,'Foreign trajectory result')
        if result['history_regime']=='WARM':
            warm+=1;need(len(result['calibration_pairs'])==8 and {pair['task_id'] for pair in result['calibration_pairs']}==set(tasks),'Own warm history did not physically acquire all eight pairs')
        else:need(not result['calibration_pairs'],'Cold history received calibration')
        need(result['allocated_shared_feature_usage']==runner.usage(profiles),'A standalone policy omits shared paid feature acquisition')
        current_ids={bound['request_id'] for bound in result['own_query_receipts']}
        need(not own_ids.intersection(current_ids),'Physical own history/query shared across strategies');own_ids.update(current_ids)
        need(result['allocated_standalone_native_query_units']==result['actual_own_physical_usage']['native_query_units']+48,'Standalone native cost omits full required old-profile acquisition')
        checked=evaluate.evaluate_trajectory(path,contracts,cells)
        rechecked.append({'trajectory_id':result['trajectory_id'],'frozen_decisions_reproduced':True,
            'own_pair_reference_mismatch_count':len(checked['own_pair_reference_mismatches']),
            'supplementary_source_recheck_mismatch_count':len(checked['source_recheck_mismatches'])})
    need(warm==10 and own_ids=={row['request_id'] for row in raw if row['phase']!='profile'},'Own strategy query exports omit or share physical operations')
    return {'audited_at_utc':datetime.now(timezone.utc).isoformat(),'audit_passed':True,
        'application_id':application,'repetition':repetition,'new_native_or_model_calls':0,
        'original_evidence_or_frozen_sources_modified':False,'completed_trajectories':20,'logical_episode_closures':60,
        'actual_native_query_units':len(raw),'native_query_ceiling':568,'paid_old_profile_queries':48,
        'own_warm_trajectories':warm,'own_warm_native_queries':160,'own_comparison_native_queries':sum(row['phase']=='comparison' for row in raw),
        'all_actual_provider_and_root_operation_joins_verified':True,'physical_usage':completion['physical_usage'],
        'original_CG1_sha256':POLICY_SHA256,'guidance_files_verified':guide_files,
        'validation_freeze_files_verified':outer_files,'main_source_closure_files_verified':main_files,
        'all_model_calls_fixed0_96_untruncated_uncached':True,'all_native_contexts_reached_actual_model':True,
        'actual_prompt_token_range':[min(lengths),max(lengths)],'actual_completion_token_range':[min(output_lengths),max(output_lengths)],
        'native_source_proofs':source_proofs,'matched_immutable_old_feature_hashes_by_episode':shared,
        'A_old_profile_acquired_after_all_episode1_closures':True,'frozen_trajectory_decision_checks':rechecked,
        'reference_state_task_cells_stable':sum(row['status']=='stable' for row in truth.values()),
        'supplementary_source_passes_posthoc':sum(row['source_metadata_pass'] for row in query_primary),
        'standalone_cost_scope':'Each policy allocation includes all required48 OLD queries and common native setup; these allocations are not additional physical queries and are not summed into campaign cost. Dify setup describes the retained indexed native platform; its original indexing/probe costs remain globally recorded.',
        'effectiveness_totals_or_frozen_success_criteria_redefined':False,
        'completed_block_sha256':sha(directory/'BLOCK_COMPLETION.json'),'audit_code_sha256':sha(Path(__file__))}

def main():
    parser=argparse.ArgumentParser()
    for name in ('run','block','reference','config','validation-freeze','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=audit(args.run,args.block,args.reference,args.config,args.validation_freeze)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('audit_passed','application_id','repetition','completed_trajectories','actual_native_query_units','paid_old_profile_queries','own_warm_native_queries','own_comparison_native_queries')},indent=2))

if __name__=='__main__':main()

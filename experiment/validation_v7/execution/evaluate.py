"""Independent saved-output evaluation of the frozen external validation design.

No native dispatch, provider request, case selection or policy fitting occurs.
"""
from collections import Counter, defaultdict
import csv
from pathlib import Path

from experiment.validation_v7.guidance import policy
from experiment.validation_v7.execution.runner import (
    ALL_ARMS, Contracts, EPISODES, STATES, StudyIncident, read, sha, usage, write_new,
)

LABELS = {(True,True):'preserved_correct',(True,False):'regression',
          (False,True):'repair',(False,False):'persistent_failure'}


def rows(path):
    return [__import__('json').loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def _bound(path,digest):
    if sha(path)!=digest: raise StudyIncident('Saved receipt changed: '+str(path))
    return read(path)


def primary_recheck(raw,contracts):
    output=raw['native_output'];state=raw['state_id'];task=raw['task_id']
    if output.get('valid_native_response') is not True or output.get('state_id')!=state:
        raise StudyIncident('Native identity/transport invalid in saved evidence')
    if raw.get('root_meter_receipt',{}).get('dispatch_safe_to_continue') is not True:
        raise StudyIncident('Unreconciled actual provider work in saved evidence')
    return contracts.check(task,output,bindings=output.get('source_bindings',[]),state=state,reference=True)


def reference_truth(reference_dir,contracts):
    directory=Path(reference_dir);completion=read(directory/'REFERENCE_COMPLETION.json')
    expected=3*len(contracts.specs)*2
    if completion.get('phase')!='reference' or completion.get('error') is not None or completion.get('outputs')!=expected or completion.get('planned_outputs')!=expected:
        raise StudyIncident('Complete independent three-state/two-pass reference bank required')
    bank=rows(directory/'sealed/reference_outputs.jsonl');groups=defaultdict(list);ids=set()
    for row in bank:
        if row['request_id'] in ids: raise StudyIncident('Duplicated reference request')
        ids.add(row['request_id'])
        if row['state_id'] not in STATES or row['task_id'] not in contracts.specs:
            raise StudyIncident('Reference outside frozen task/state frame')
        raw=_bound(row['receipt_path'],row['receipt_sha256'])
        if any(raw[key]!=row[key] for key in ('request_id','state_id','task_id','application_id')):
            raise StudyIncident('Reference metadata differs from native receipt')
        checked=primary_recheck(raw,contracts)
        if checked['primary_pass']!=row['reference_check']['primary_pass']:
            raise StudyIncident('Independent primary checker differs from saved reference judgment')
        groups[row['state_id'],row['task_id']].append(row)
    truth={}
    for state in STATES:
        for task in contracts.specs:
            observations=groups[state,task]
            complete=len(observations)==2 and {row['repetition'] for row in observations}=={1,2}
            flags=[row['reference_check']['primary_pass'] for row in observations]
            status='incomplete' if not complete else ('stable' if len(set(flags))==1 else 'uncertain')
            truth[state,task]={'status':status,'primary_pass':flags[0] if status=='stable' else None}
    cells=[]
    for episode,old,new in EPISODES:
        for task in contracts.specs:
            before,after=truth[old,task],truth[new,task]
            label=('incomplete' if 'incomplete' in (before['status'],after['status']) else
                   'uncertain' if 'uncertain' in (before['status'],after['status']) else
                   LABELS[before['primary_pass'],after['primary_pass']])
            cells.append({'episode_index':episode,'task_id':task,'old_state':old,'new_state':new,'classification':label})
    return truth,cells


def expected_history(result,episode):
    pairs=[*result['calibration_pairs'],*[row for row in result['selected_pairs'] if row['episode_index']<episode]]
    return [{'source':'own_observed_paired_execution','trajectory_id':result['trajectory_id'],
             'task_id':row['task_id'],'episode_index':row['episode_index'],'selected':True,
             'timely':row['timely'],'old_primary_pass':row['old_primary_pass'],'new_primary_pass':row['new_primary_pass'],
             'changed_tokens':result['changed_tokens_by_episode'][str(max(row['episode_index'],1))],
             'receipt_sha256':row['receipt_sha256']} for row in pairs]


def evaluate_trajectory(path,contracts,cells):
    path=Path(path);result=read(path);owner=result['trajectory_id']
    if result.get('error') is not None or result.get('complete') is not True:
        raise StudyIncident('Incomplete/incident trajectory cannot silently enter valid comparison')
    if result['arm'] not in ALL_ARMS or result['history_regime'] not in ('COLD','WARM'):
        raise StudyIncident('Unknown policy/history regime')
    expected={(row['episode_index'],row['task_id']):row['classification'] for row in cells}
    targets={key for key,label in expected.items() if label=='regression'}
    own={};source_mismatches=[]
    for bound in result['own_query_receipts']:
        raw=_bound(bound['receipt_path'],bound['receipt_sha256'])
        if raw['trajectory_id']!=owner or raw['application_id']!=result['application_id']:
            raise StudyIncident('Foreign native query included in own trajectory')
        for field in ('request_id','state_id','task_id','phase'):
            if raw[field]!=bound[field]: raise StudyIncident('Own raw-query metadata mismatch')
        if raw['request_id'] in own: raise StudyIncident('Duplicate physical own query')
        own[raw['request_id']]=(raw,primary_recheck(raw,contracts))
    actual_usage=usage([row for row,checked in own.values()])
    if actual_usage!=result['actual_own_physical_usage']:
        raise StudyIncident('Own physical work differs from joined native receipt costs')
    for pair in [*result['calibration_pairs'],*result['selected_pairs']]:
        disk=_bound(pair['receipt_path'],pair['receipt_sha256'])
        if disk!={key:value for key,value in pair.items() if key not in ('receipt_path','receipt_sha256')}:
            raise StudyIncident('Selected pair export differs from its durable record')
        if pair['trajectory_id']!=owner: raise StudyIncident('Foreign pair in trajectory')
        if pair['phase']=='calibration':
            if pair['episode_index']!=0 or (pair['old_state'],pair['new_state'])!=('HEALTHY','A_BAD'):
                raise StudyIncident('Calibration states/phase differ from frozen design')
        elif pair['phase']=='comparison':
            allowed={episode:(old,new) for episode,old,new in EPISODES}
            if allowed.get(pair['episode_index'])!=(pair['old_state'],pair['new_state']):
                raise StudyIncident('Comparison state pair differs from its frozen logical episode')
        else: raise StudyIncident('A profile/reference pair cannot become an operational outcome')
        for side in ('old','new'):
            raw,checked=own[pair[side+'_request_id']]
            if (raw['state_id']!=pair[side+'_state'] or raw['task_id']!=pair['task_id']
                    or checked['primary_pass']!=pair[side+'_primary_pass']):
                raise StudyIncident('Independent selected-output factual check differs')
            if checked['source_metadata_pass']!=pair[side+'_source_metadata_pass']:
                source_mismatches.append({'request_id':raw['request_id'],'channel':'supplementary_source'})
        for key in ('timely','primary_alarm_candidate','primary_alarm_credited','old_primary_pass','new_primary_pass'):
            if type(pair[key]) is not bool: raise StudyIncident('Malformed saved pair judgment')
        candidate=pair['old_primary_pass'] and not pair['new_primary_pass']
        if pair['primary_alarm_candidate']!=candidate or pair['primary_alarm_credited']!=(candidate and pair['timely']):
            raise StudyIncident('Pair credit violates factual/timely guard')
    calibration=len(result['calibration_pairs'])
    if calibration!=(12 if result['history_regime']=='WARM' else 0):
        raise StudyIncident('Own full warm calibration/empty cold start violated')
    if sum(row['phase']=='calibration' for row,checked in own.values())!=2*calibration:
        raise StudyIncident('Warm history does not have its own physically executed paired receipts')
    if len(result['decisions'])!=3 or len(result['episodes'])!=3:
        raise StudyIncident('Frozen three-episode frame incomplete')
    chosen_arms=[]
    for decision in result['decisions']:
        episode=decision['episode_index'];features=_bound(decision['feature_receipt_path'],decision['feature_receipt_sha256'])
        impact_row=_bound(decision['impact_receipt']['receipt_path'],decision['impact_receipt']['receipt_sha256'])
        history=expected_history(result,episode)
        if decision['history_before_decision']!=history:
            raise StudyIncident('Decision history differs from earlier OWN selected physical pair records')
        if features['release_episode']>episode or features['state_id']!=decision['old_state']:
            raise StudyIncident('Future/new-state feature exposure')
        task_ids=features['task_ids']
        if set(task_ids)!=set(contracts.specs): raise StudyIncident('Paid public catalog differs from frozen contract identities')
        positive=policy.checked_history(history,contracts.specs,owner,episode)
        admitted,reason=policy.checked_impact(impact_row['impact'],task_ids,decision['changed_tokens'],
                                             features['feature_block_id'],episode)
        if result['arm']=='CG1':
            recomputed=policy.choose(task_ids,features['pair_cost_seconds'],impact_row['impact'],history,
                trajectory_id=owner,feature_block_id=features['feature_block_id'],episode_index=episode,
                changed_tokens=decision['changed_tokens'],pair_limit=decision['pair_limit'])
            if any(decision.get(key)!=value for key,value in recomputed.items()):
                raise StudyIncident('Frozen CG1 decision is not reproducible from predecision data')
            arm=recomputed['chosen_arm'];order=recomputed['nominal_ordered_task_ids']
        else:
            arm=result['arm'];counts=dict(Counter(row['task_id'] for row in positive))
            order=policy.rank_arm(task_ids,features['pair_cost_seconds'],admitted,counts,arm)
        if decision['chosen_arm']!=arm or decision['nominal_ordered_task_ids']!=order:
            raise StudyIncident('Fixed baseline or chosen-arm ranking changed')
        chosen_arms.append(arm)
        for pair in result['selected_pairs']:
            if pair['episode_index']==episode and pair['timely'] and pair['judgment_observed_elapsed_seconds']>decision['deadline_elapsed_seconds']:
                raise StudyIncident('Saved timely credit arrived after its episode deadline')
    selected={};alarms=set();mismatches=[]
    for pair in result['selected_pairs']:
        key=pair['episode_index'],pair['task_id']
        if key not in expected or key in selected: raise StudyIncident('Comparison outside frame or duplicated')
        selected[key]=pair
        if pair['primary_alarm_credited']: alarms.add(key)
        observed=LABELS[pair['old_primary_pass'],pair['new_primary_pass']]
        if expected[key] not in ('incomplete','uncertain') and observed!=expected[key]:
            mismatches.append({'episode_index':key[0],'task_id':key[1],'own_pair':observed,'reference':expected[key]})
    discordant={key for key in alarms-targets if expected[key] not in ('incomplete','uncertain')}
    repair_alarms={key for key in alarms if expected[key]=='repair'}
    admission_misses=[]
    for decision in result['decisions']:
        for episode,task in targets:
            if episode==decision['episode_index'] and task not in decision['admitted_task_ids']:
                admission_misses.append({'episode_index':episode,'task_id':task})
    per_episode=[]
    for episode,old,new in EPISODES:
        target={key for key in targets if key[0]==episode}
        per_episode.append({'episode_index':episode,'target_cells':len(target),'detected':len(target&alarms),
                            'missed':len(target-alarms),'credited_alarms':sum(key[0]==episode for key in alarms)})
    return {'trajectory_id':owner,'application_id':result['application_id'],'arm':result['arm'],
        'budget_id':result['budget_id'],'history_regime':result['history_regime'],'repetition':result['repetition'],
        'reference_regression_cells':len(targets),'detected':len(targets&alarms),'missed':len(targets-alarms),
        'credited_alarms':len(alarms),'reference_discordant_alarms':len(discordant),'repair_alarms':len(repair_alarms),
        'own_pair_reference_mismatches':mismatches,'evidence_admission_misses':admission_misses,
        'alarms_with_uncertain_reference':sum(expected[key] in ('incomplete','uncertain') for key in alarms),
        'source_recheck_mismatches':source_mismatches,'selected_comparison_pairs':len(selected),
        'timely_comparison_pairs':sum(pair['timely'] for pair in selected.values()),
        'actual_own_physical_usage':actual_usage,
        'allocated_standalone_native_query_units':result['allocated_standalone_native_query_units'],
        'allocated_standalone_wall_seconds':result['allocated_standalone_wall_seconds'],
        'chosen_arm_distribution':dict(Counter(chosen_arms)),
        'nominal_actual_schedule_deviations':sum(not row['nominal_actual_selection_equal'] for row in result['episodes']),
        'deadline_overrun_seconds':sum(row['deadline_overrun_seconds'] for row in result['episodes']),
        'per_episode':per_episode,'source_and_primary_receipts_independently_checked':True,
        'timeliness_is_saved_event_implementation_audit_not_independent_clock_remeasurement':True}


def matched_strata(evaluations):
    groups=defaultdict(lambda:defaultdict(list))
    for row in evaluations:
        groups[row['application_id'],row['budget_id'],row['history_regime']][row['arm']].append(row)
    result=[]
    for (app,budget,regime),arms in sorted(groups.items()):
        complete=set(arms)==set(ALL_ARMS) and all(len(group)==2 and {r['repetition'] for r in group}=={1,2} for group in arms.values())
        if not complete:
            result.append({'application_id':app,'budget_id':budget,'history_regime':regime,'complete':False});continue
        totals={arm:{key:sum(row[key] for row in group) for key in (
            'detected','missed','credited_alarms','reference_discordant_alarms','repair_alarms',
            'allocated_standalone_native_query_units','allocated_standalone_wall_seconds')} for arm,group in arms.items()}
        guided,combined=totals['CG1'],totals['I1_H1']
        retained=(guided['detected']>=combined['detected'] and
                  guided['reference_discordant_alarms']<=combined['reference_discordant_alarms'] and
                  guided['repair_alarms']<=combined['repair_alarms'])
        utility=(guided['detected']>combined['detected'] or
                 guided['detected']==combined['detected'] and
                 guided['allocated_standalone_native_query_units']<combined['allocated_standalone_native_query_units'])
        family=[]
        for episode,_,_ in EPISODES:
            gd=sum(part['detected'] for row in arms['CG1'] for part in row['per_episode'] if part['episode_index']==episode)
            cd=sum(part['detected'] for row in arms['I1_H1'] for part in row['per_episode'] if part['episode_index']==episode)
            family.append({'episode_index':episode,'CG1_detected':gd,'combined_detected':cd,'guided_loss':gd<cd})
        result.append({'application_id':app,'budget_id':budget,'history_regime':regime,'complete':True,
            'totals':totals,'directional_retention':retained,'strict_selection_utility_before_retention_gate':utility,
            'per_episode_diagnostics':family,'family_specific_losses_must_not_be_hidden_by_aggregate_gain':any(x['guided_loss'] for x in family)})
    return result


def evaluate_campaign(reference_dirs,contract_documents,result_paths,output_dir,*,expected_apps=2,expected_trajectories=80):
    if set(reference_dirs)!=set(contract_documents): raise StudyIncident('Application reference/contract frames differ')
    applications={};contracts={}
    for app,directory in reference_dirs.items():
        contracts[app]=Contracts(contract_documents[app]);truth,cells=reference_truth(directory,contracts[app])
        applications[app]={'reference_cells':cells,'reference_cell_counts':dict(Counter(row['classification'] for row in cells)),
                           'state_cell_stability':dict(Counter(row['status'] for row in truth.values()))}
    evaluations=[];raw_results=[]
    for path in result_paths:
        raw=read(path);app=raw['application_id']
        if app not in applications: raise StudyIncident('Unregistered application')
        evaluations.append(evaluate_trajectory(path,contracts[app],applications[app]['reference_cells']))
        raw_results.append(raw)
    identities=[(r['application_id'],r['arm'],r['budget_id'],r['history_regime'],r['repetition']) for r in evaluations]
    if len(identities)!=len(set(identities)): raise StudyIncident('Duplicate comparison trajectory identity')
    feature_groups=defaultdict(set)
    for raw in raw_results:
        for decision in raw['decisions']:
            feature_groups[raw['application_id'],raw['repetition'],decision['episode_index']].add(
                (decision['feature_receipt_sha256'],decision['impact_receipt']['receipt_sha256']))
    if any(len(values)!=1 for values in feature_groups.values()):
        raise StudyIncident('Matched strategies did not receive identical common old features')
    strata=matched_strata(evaluations)
    complete=(len(applications)==expected_apps and len(evaluations)==expected_trajectories
              and len(strata)==expected_apps*4 and all(row['complete'] for row in strata))
    adequacy={app:{str(episode):sum(row['episode_index']==episode and row['classification']=='regression'
                  for row in values['reference_cells']) for episode in (1,3)} for app,values in applications.items()}
    adequate=bool(adequacy) and all(all(value>=1 for value in per_episode.values()) for per_episode in adequacy.values())
    retention=complete and adequate and all(row['directional_retention'] for row in strata)
    utility=retention and any(row['strict_selection_utility_before_retention_gate'] for row in strata)
    summary={'phase':'EXTERNAL_V7','scope':'Prospective transfer of frozen CG1 to independent native implementations with controlled factual workloads.',
        'application_count':len(applications),'trajectory_count':len(evaluations),'complete_frozen_frame':complete,
        'applications':applications,'trajectories':evaluations,'matched_strata':strata,
        'matched_old_feature_hash_blocks':len(feature_groups),'identical_common_features_confirmed':True,
        'reference_fault_opportunity_counts':adequacy,'adequate_stable_opportunity_in_both_families':adequate,
        'prospective_directional_retention':retention,'prospective_selection_utility':utility,
        'family_specific_loss_present':any(row.get('family_specific_losses_must_not_be_hidden_by_aggregate_gain',False) for row in strata),
        'interpretation':('Retention and selection-utility criteria met in the frozen finite frame.' if utility else
                          'Retention met but no added selection utility demonstrated.' if retention else
                          'Frozen-frame retention not established; report operating limits/incomplete cells.'),
        'population_significance_or_universal_portability_claim':False,
        'new_native_or_provider_queries':0,'input_result_sha256':{str(Path(path).resolve()):sha(path) for path in result_paths}}
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=False);write_new(output/'SUMMARY.json',summary)
    compact=[{key:row[key] for key in ('trajectory_id','application_id','arm','budget_id','history_regime','repetition',
             'detected','missed','reference_regression_cells','reference_discordant_alarms','repair_alarms',
             'allocated_standalone_native_query_units','allocated_standalone_wall_seconds')} for row in evaluations]
    if compact:
        with (output/'TRAJECTORIES.csv').open('x',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(compact[0]));writer.writeheader();writer.writerows(compact)
    return summary

"""Independent pure v8 saved-output analysis; no dispatch or policy fitting."""
from collections import Counter, defaultdict
from pathlib import Path
import csv
from experiment.development_v8.acquisition import SCOPE_FIELDS
from experiment.development_v8.execution import evaluate as frozen
from experiment.development_v8.execution.runner import ROOT, StudyIncident, read, sha, usage, utc, write_new
from experiment.development_v8.execution.preflight import load_case, refresh_preflight
from experiment.validation_v7.execution.source_channels import CanonicalContracts


def audit_raw_role(raw,*,application,phase,require_native_identity=True):
    native=raw.get('native_output',{});receipt=raw.get('root_meter_receipt',{})
    reservation=receipt.get('native_reservation') or {};metadata=reservation.get('metadata') or {}
    if raw.get('application_id')!=application or raw.get('phase')!=phase:
        raise StudyIncident('Actual main query belongs to another application/role')
    for key in ('request_id','state_id','task_id'):
        if metadata.get(key)!=raw.get(key) or (require_native_identity and native.get(key)!=raw.get(key)):
            raise StudyIncident('Native/wrapper/reserved main identity differs')
    for key in ('application_id','phase','trajectory_id','episode_index',*SCOPE_FIELDS):
        if metadata.get(key)!=raw.get(key):raise StudyIncident('Actual main scope/role/owner differs from reservation')
    if (any(native.get(key)!=raw.get(key) for key in SCOPE_FIELDS)
            or raw.get('cohort_id')!='validation' or native.get('valid_native_response') is not True
            or receipt.get('dispatch_safe_to_continue') is not True
            or receipt.get('native_query_units_reserved')!=1
            or receipt.get('provider_join',{}).get('joined') is not True
            or reservation.get('request_id')!=raw.get('request_id')
            or receipt.get('allocation_id')!=raw.get('request_id')):
        raise StudyIncident('Invalid/unjoined/scoped main native query')


def block_dir(value):
    directory=Path(value).resolve()
    choices=[path for path in (directory,directory/'block') if (path/'BLOCK_COMPLETION.json').is_file()]
    if len(choices)!=1:raise StudyIncident('One exact completed application/repetition directory required')
    return choices[0]


def audit_block_physical(directory,completion):
    """Reconcile all actual raw work, including paid profiles and setup."""
    directory=Path(directory);meter=directory.parent/'meter'
    if not (meter/'SETUP.json').is_file():raise StudyIncident('Explicit driver meter setup receipt missing')
    queries=[read(path) for path in sorted((meter/'raw').glob('*.json'))]
    operations=[read(meter/'SETUP.json')]
    operations += [read(path) for path in sorted((meter/'setup_steps').glob('*.json'))]
    if (meter/'CLEANUP.json').is_file():operations.append(read(meter/'CLEANUP.json'))
    identifiers=set()
    for raw in queries:
        if raw['request_id'] in identifiers:raise StudyIncident('Duplicate physical query in block meter')
        identifiers.add(raw['request_id'])
        audit_raw_role(raw,application=completion['application_id'],phase=raw['phase'],
                       require_native_identity=raw['phase']!='setup_probe')
        if raw['phase'] not in ('profile','calibration','comparison'):
            raise StudyIncident('Reference/qualification queries cannot enter a main block allocation')
    actual=usage([*queries,*operations])
    if actual!=completion['physical_usage']:raise StudyIncident('Saved block physical total differs from joined raw/setup costs')
    profiles=[row for row in queries if row['phase']=='profile']
    if len(profiles)!=48:raise StudyIncident('Every block requires both24-query paid OLD profiles')
    required={(state,task) for state in ('HEALTHY','A_BAD') for task in {r['task_id'] for r in profiles}}
    counts=Counter((row['state_id'],row['task_id']) for row in profiles)
    if len(required)!=16 or set(counts)!=required or any(count!=3 for count in counts.values()):
        raise StudyIncident('Common OLD profiles must contain exactly three native passes of all eight tasks')
    return {'meter_dir':str(meter),'query_receipt_count':len(queries),'actual_physical_usage':actual,
        'all_profile_setup_and_own_costs_independently_reconciled':True}


def summarize(applications,evaluations,raw_results,result_paths):
    """Same frozen finite-frame criteria; no threshold or policy fitting."""
    identities=[(r['application_id'],r['arm'],r['budget_id'],r['history_regime'],r['repetition']) for r in evaluations]
    if len(identities)!=len(set(identities)): raise StudyIncident('Duplicate comparison trajectory identity')
    groups=defaultdict(set)
    for raw in raw_results:
        for decision in raw['decisions']:
            groups[raw['application_id'],raw['repetition'],decision['episode_index']].add(
                (decision['feature_receipt_sha256'],decision['impact_receipt']['receipt_sha256']))
    if any(len(values)!=1 for values in groups.values()): raise StudyIncident('Matched strategies received different paid old features')
    strata=frozen.matched_strata(evaluations)
    complete=(set(applications)=={'openwebui','dify'} and len(evaluations)==80 and len(strata)==8 and all(r['complete'] for r in strata))
    adequacy={app:{str(ep):sum(r['episode_index']==ep and r['classification']=='regression' for r in value['reference_cells'])
                  for ep in (1,3)} for app,value in applications.items()}
    adequate=bool(adequacy) and all(all(n>=1 for n in value.values()) for value in adequacy.values())
    retention=complete and adequate and all(r['directional_retention'] for r in strata)
    utility=retention and any(r['strict_selection_utility_before_retention_gate'] for r in strata)
    return {'phase':'EXTERNAL_V8','scope':'Held-out-workload transfer of unchanged CG1 in two developed native implementations with controlled factual workloads.',
        'application_count':len(applications),'trajectory_count':len(evaluations),'complete_frozen_frame':complete,
        'applications':applications,'trajectories':evaluations,'matched_strata':strata,
        'matched_old_feature_hash_blocks':len(groups),'identical_common_features_confirmed':True,
        'reference_fault_opportunity_counts':adequacy,'adequate_stable_opportunity_in_both_families':adequate,
        'prospective_directional_retention':retention,'prospective_selection_utility':utility,
        'family_specific_loss_present':any(r.get('family_specific_losses_must_not_be_hidden_by_aggregate_gain',False) for r in strata),
        'interpretation':('Retention and selection-utility criteria met in the frozen finite frame.' if utility else
                          'Retention met but no added selection utility demonstrated.' if retention else
                          'Frozen-frame retention not established; report operating limits/incomplete cells.'),
        'population_significance_or_universal_portability_claim':False,'new_native_or_provider_queries':0,
        'input_result_sha256':{str(Path(path).resolve()):sha(path) for path in result_paths}}



def evaluate_main(validation_freeze,index_path,block_dirs,output):
    if index_path is None or len(block_dirs)!=4:
        raise StudyIncident('Current preflight and all four explicit main blocks are required')
    index=refresh_preflight(index_path,validation_freeze)
    cases={app:load_case(validation_freeze,app) for app in ('openwebui','dify')}
    applications={};contracts={}
    for app,case in cases.items():
        contracts[app]=CanonicalContracts(case['contract_document'])
        gate=read(index['applications'][app]['reference']['gate_path'])
        truth,cells=frozen.reference_truth(gate['acquisition_dir'],contracts[app])
        applications[app]={'reference_cells':cells,
            'reference_cell_counts':dict(Counter(row['classification'] for row in cells)),
            'state_cell_stability':dict(Counter(row['status'] for row in truth.values()))}
    evaluations=[];raw_results=[];paths=[];identities=set();physical=[]
    for value in block_dirs:
        directory=block_dir(value);completion=read(directory/'BLOCK_COMPLETION.json')
        identity=completion.get('application_id'),completion.get('repetition')
        if identity in identities or identity not in {(app,rep) for app in cases for rep in (1,2)}:
            raise StudyIncident('Duplicate/foreign main application/repetition')
        identities.add(identity)
        if completion.get('error') is not None or completion.get('completed_trajectories')!=20 or completion.get('planned_trajectories')!=20:
            raise StudyIncident('Incomplete block cannot establish the prospectively fixed effectiveness criteria')
        metering=audit_block_physical(directory,completion)
        for raw_path in (Path(metering['meter_dir'])/'raw').glob('*.json'):
            raw=read(raw_path)
            if any(raw.get(key)!=expected for key,expected in cases[identity[0]]['scope'].items()):
                raise StudyIncident('Main query uses another selected validation configuration')
        selected=list((directory/'trajectories').glob('*/TRAJECTORY_RESULT.json'))
        if len(selected)!=20:raise StudyIncident('Main block has another complete trajectory frame')
        for path in selected:
            raw=read(path)
            if (raw['application_id'],raw['repetition'])!=identity:raise StudyIncident('Foreign main trajectory')
            for bound in raw['own_query_receipts']:
                evidence=frozen._bound(bound['receipt_path'],bound['receipt_sha256'])
                audit_raw_role(evidence,application=identity[0],phase=evidence['phase'])
                if evidence['phase'] not in ('calibration','comparison'):
                    raise StudyIncident('Profiles/references cannot become own operational history')
            evaluations.append(frozen.evaluate_trajectory(path,contracts[identity[0]],applications[identity[0]]['reference_cells']))
            raw_results.append(raw);paths.append(path)
        physical.append({'application_id':identity[0],'repetition':identity[1],
            'block_completion_path':str(directory/'BLOCK_COMPLETION.json'),
            'block_completion_sha256':sha(directory/'BLOCK_COMPLETION.json'),**metering})
    summary=summarize(applications,evaluations,raw_results,paths)
    summary.update({'validation_freeze_sha256':sha(validation_freeze),'preflight_index_sha256':sha(index_path),
        'physical_block_usage':physical,'same_retention_and_utility_formulas_as_v7':True,
        'standalone_allocations_not_summed_as_physical_work':True,
        'freshness_scope':'Fresh workloads in the same developed applications and historical fault families'})
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    write_new(output/'SUMMARY.json',summary)
    fields=('trajectory_id','application_id','arm','budget_id','history_regime','repetition','detected','missed',
            'reference_regression_cells','reference_discordant_alarms','repair_alarms',
            'allocated_standalone_native_query_units','allocated_standalone_wall_seconds')
    with (output/'TRAJECTORIES.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        writer.writerows({key:row[key] for key in fields} for row in evaluations)
    write_new(output/'EVALUATION_PROVENANCE.json',{'at_utc':utc(),'new_native_or_model_queries':0,
        'analysis_source_sha256':sha(Path(__file__)),'eight_task_evaluator_sha256':sha(Path(frozen.__file__)),
        'canonical_source_projection_sha256':sha(ROOT/'experiment/validation_v7/execution/source_channels.py')})
    return summary

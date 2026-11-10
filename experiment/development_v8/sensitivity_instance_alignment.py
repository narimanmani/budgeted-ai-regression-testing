"""POSTHOC within-index reference-alignment sensitivity; no native dispatch.

Original reference banks, primary scores, frozen criteria and decisions remain
unchanged. This is an explicit observed-instance assumption, not new gold or an
alternative-oracle experiment. It cannot rescue the original primary result.
"""
from copy import deepcopy
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import argparse
import hashlib
import json

from experiment.development_v8.execution import evaluate as frozen
from experiment.validation_v7.execution.source_channels import CanonicalContracts

ROOT=Path(__file__).resolve().parents[2]
TARGET={'application_id':'openwebui','repetition':2,'task_id':'VOW07','state_id':'A_BAD'}
OVERRIDES={1:'regression',2:'repair'}
SOURCE_FILES=('experiment/development_v8/execution/evaluate.py',
 'experiment/development_v8/execution/analysis.py','experiment/development_v8/execution/runner.py',
 'experiment/validation_v7/execution/runner.py','experiment/validation_v7/execution/source_channels.py',
 'experiment/validation_v7/guidance/policy.py','experiment/native_v3/common/contracts.py',
 'experiment/native_v3/common/reference.py')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,ensure_ascii=True);stream.write('\n')
def need(condition,message):
    if not condition:raise ValueError(message)


def aligned_cells(cells,application,repetition):
    """Only two labels change, only in the specified native instance."""
    result=deepcopy(cells)
    if (application,repetition)!=(TARGET['application_id'],TARGET['repetition']):return result
    changed=[]
    for row in result:
        if row['task_id']==TARGET['task_id'] and row['episode_index'] in OVERRIDES:
            need(row['classification']=='preserved_correct','Sensitivity requires original preserved-correct cells')
            row['classification']=OVERRIDES[row['episode_index']];changed.append(row['episode_index'])
    need(sorted(changed)==[1,2],'Exactly the original E1/E2 target cells are required')
    return result


def verify_override_evidence(forensic_path,primary_path,contracts):
    forensic=read(forensic_path)
    need(forensic.get('audit_passed') is True and forensic.get('new_native_or_provider_queries')==0
         and forensic.get('primary_evaluation_or_frozen_files_modified') is False,'Completed read-only forensic receipt required')
    need(forensic.get('primary_evaluation_sha256')==sha(primary_path),'Forensics bind another primary result')
    need(forensic.get('unique_task_ids')==[TARGET['task_id']],'The sensitivity may address only the declared task')
    groups=[row for row in forensic['groups'] if row['frame']=='main-openwebui-r2' and row['state_id']=='A_BAD']
    need(len(groups)==1,'One exact affected native-index group required');group=groups[0]
    need(group['task_id']==TARGET['task_id'] and group['primary_counts']=={'False':39}
         and group['role_counts'].get('profile')==3 and group['operational_and_reference_primary_flags_agree'] is True,
         'Observed39-query index pattern and three OLD proofs required')
    observations=[row for row in forensic['actual_raw_evidence'] if row['frame']=='main-openwebui-r2'
                  and row['task_id']==TARGET['task_id'] and row['state_id']=='A_BAD']
    need(len(observations)==39 and all(row['primary_pass'] is False for row in observations),'Complete observed index-specific failure pattern required')
    old=[row for row in observations if row['phase']=='profile'];need(len(old)==3,'Exactly three paid OLD observations required')
    setup=Path(group['native_setup_file']);need(sha(setup)==group['native_setup_sha256'],'Native-index setup proof changed')
    proofs=[];ids=set()
    for pointer in old:
        raw_path=Path(pointer['raw_file']);need(sha(raw_path)==pointer['raw_sha256'],'OLD raw proof changed');raw=read(raw_path)
        native=raw['native_output'];receipt=raw['root_meter_receipt'];metadata=receipt['native_reservation']['metadata']
        need(raw['request_id'] not in ids and raw['request_id']==pointer['request_id'],'OLD proof duplicated or foreign');ids.add(raw['request_id'])
        need(raw['application_id']=='openwebui' and raw['repetition']==2 and raw['phase']=='profile'
             and raw['episode_index']==2 and raw['task_id']=='VOW07' and raw['state_id']=='A_BAD'
             and raw['trajectory_id']=='openwebui-r2-OLD-A_BAD','Only paid logical OLD observations may justify override')
        need(native['workspace_id']==group['native_collection_id'] and native.get('valid_native_response') is True,
             'OLD evidence belongs to another native index or failed transport')
        for key in ('request_id','state_id','task_id','application_id','phase','trajectory_id','episode_index',
                    'cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256'):
            need(metadata.get(key)==raw.get(key),'OLD reservation identity differs')
        need(receipt.get('dispatch_safe_to_continue') is True and receipt.get('native_query_units_reserved')==1
             and receipt.get('provider_join',{}).get('joined') is True,'OLD proof is not paid/reconciled')
        sealed=read(receipt['receipt_path'])
        need({k:v for k,v in receipt.items() if k!='main_admission_guard'}==sealed,'OLD canonical root seal differs')
        native_path=Path(native['receipt_path']);need(sha(native_path)==native['receipt_sha256'],'OLD original native proof changed')
        original=read(native_path)
        for key in ('request_id','state_id','task_id','workspace_id','answer','completed','native_response','source_bindings'):
            need(original.get(key)==native.get(key),'Original native/wrapper OLD payload differs')
        operational=contracts.check('VOW07',native,bindings=native['source_bindings'],state='A_BAD')
        independent=contracts.check('VOW07',native,bindings=native['source_bindings'],state='A_BAD',reference=True)
        need(operational['primary_pass'] is False and independent['primary_pass'] is False
             and native['answer']==pointer['answer'] and native['answer'] in group['answer_counts'],
             'OLD format violation not reproduced by unchanged factual checks')
        proofs.append({'request_id':raw['request_id'],'raw_file':str(raw_path),'raw_sha256':sha(raw_path),
            'native_receipt_path':str(native_path),'native_receipt_sha256':sha(native_path),
            'root_joined_receipt_path':receipt['receipt_path'],'root_joined_receipt_sha256':sha(receipt['receipt_path']),
            'state_id':'A_BAD','task_id':'VOW07','answer':native['answer'],
            'operational_primary_pass':False,'independent_primary_pass':False})
    return {'forensic_receipt_path':str(Path(forensic_path).resolve()),'forensic_receipt_sha256':sha(forensic_path),
        'native_setup_path':str(setup),'native_setup_sha256':sha(setup),'native_collection_id':group['native_collection_id'],
        'observed_index_format_failures':39,'paid_OLD_profile_proofs':proofs}


def totals(evaluations):
    result={}
    for arm in frozen.ALL_ARMS:
        rows=[row for row in evaluations if row['arm']==arm]
        result[arm]={key:sum(row[key] for row in rows) for key in ('detected','missed','reference_regression_cells',
            'credited_alarms','reference_discordant_alarms','repair_alarms','allocated_standalone_native_query_units')}
        result[arm]['operational_reference_pair_mismatches']=sum(len(row['own_pair_reference_mismatches']) for row in rows)
    return result


def run(primary_path,forensic_path,validation_freeze,output):
    primary_path=Path(primary_path).resolve();output=Path(output).resolve();need(not output.exists(),'Sensitivity output must be new')
    primary_sha=sha(primary_path);primary=read(primary_path);need(primary.get('complete_frozen_frame') is True
        and primary.get('trajectory_count')==80,'Complete unchanged original primary80 required')
    outer=read(validation_freeze);source_hashes={name:sha(ROOT/name) for name in SOURCE_FILES}
    committed={str(Path(name if Path(name).is_absolute() else ROOT/name).resolve()):digest for name,digest in outer['files_sha256'].items()}
    need(all(committed.get(str((ROOT/name).resolve()))==digest for name,digest in source_hashes.items()),'Unchanged evaluator/policy/checker source closure required')
    contract_paths={app:ROOT/f'experiment/development_v8/workloads/validation/{app}/contracts.json' for app in ('openwebui','dify')}
    contracts={app:CanonicalContracts(read(path)) for app,path in contract_paths.items()}
    evidence=verify_override_evidence(forensic_path,primary_path,contracts['openwebui'])
    original_by_id={row['trajectory_id']:row for row in primary['trajectories']};evaluated=[];paths=[];labels={};original_rechecked=[]
    for name,expected_sha in primary['input_result_sha256'].items():
        path=Path(name);need(sha(path)==expected_sha,'Original trajectory bytes changed');raw=read(path);app=raw['application_id'];rep=raw['repetition']
        base=primary['applications'][app]['reference_cells'];original=frozen.evaluate_trajectory(path,contracts[app],base)
        need(original==original_by_id[raw['trajectory_id']],'Unchanged evaluator did not reproduce original primary trajectory')
        original_rechecked.append(original)
        cells=aligned_cells(base,app,rep);labels[f'{app}-r{rep}']=cells
        evaluated.append(frozen.evaluate_trajectory(path,contracts[app],cells));paths.append(str(path))
    need(len(evaluated)==80 and len({r['trajectory_id'] for r in evaluated})==80,'The exact original80 frame is required')
    strata=frozen.matched_strata(evaluated);need(len(strata)==8 and all(row['complete'] for row in strata),'All eight original matched strata required')
    retention=all(row['directional_retention'] for row in strata)
    utility=retention and any(row['strict_selection_utility_before_retention_gate'] for row in strata)
    summary={'analysis':'POSTHOC_OBSERVED_NATIVE_INDEX_STATE_ALIGNMENT','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'primary_analysis_unchanged':True,'rescue_or_replacement_of_primary_analysis':False,
        'assumption':{'target':TARGET,'only_reference_label_overrides':{'E1':'preserved_correct -> regression','E2':'preserved_correct -> repair'},
            'E3_and_all_other_cells':'unchanged','scope':'Observed within-index output-format noncompliance; not new gold or a population-accuracy estimate',
            'alternative_oracle_experiment':False,'policy_inputs_or_history_recomputed_from_reference_labels':False},
        'primary_summary_path':str(primary_path),'primary_summary_sha256':primary_sha,
        'validation_freeze_path':str(Path(validation_freeze).resolve()),'validation_freeze_sha256':sha(validation_freeze),
        'source_files_sha256':source_hashes,'analysis_source_sha256':sha(__file__),
        'contract_files_sha256':{str(path):sha(path) for path in contract_paths.values()},'override_evidence':evidence,
        'trajectory_count':80,'original_totals_independently_reproduced':totals(original_rechecked),
        'sensitivity_totals':totals(evaluated),'matched_strata':strata,
        'prospective_formula_retention_under_posthoc_assumption':retention,
        'prospective_formula_utility_under_posthoc_assumption':utility,
        'original_retention':primary['prospective_directional_retention'],'original_utility':primary['prospective_selection_utility'],
        'qualitative_retention_or_utility_conclusion_changed':retention!=primary['prospective_directional_retention'] or utility!=primary['prospective_selection_utility'],
        'family_specific_loss_vs_always_combined':any(row['family_specific_losses_must_not_be_hidden_by_aggregate_gain'] for row in strata),
        'new_native_or_provider_queries':0,'original_input_result_sha256':primary['input_result_sha256'],
        'classification_is_posthoc_sensitivity_not_original_reference_truth':True}
    need(sha(primary_path)==primary_sha and all(sha(ROOT/name)==digest for name,digest in source_hashes.items()),'Original primary/source changed during analysis')
    output.mkdir(parents=True,exist_ok=False)
    write_new(output/'SUMMARY.json',summary);write_new(output/'TRAJECTORY_EVALUATIONS.json',evaluated)
    write_new(output/'REFERENCE_CELLS_BY_INSTANCE.json',labels)
    write_new(output/'README.json',{'status':'POSTHOC_SENSITIVITY_ONLY','primary_replaced':False,
        'interpretation':'Reclassification uses the observed repetition2 A_BAD index format failure, including three paid OLD proofs. It does not add cases or change the factual checker. Original primary results remain the result of record.',
        'source_events_are_not_independent_new_defects':True,'new_native_queries':0})
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();root=args.run.resolve()
    result=run(root/'evaluation/SUMMARY.json',root/'audits/OPENWEBUI_REFERENCE_MISMATCH_FORENSICS.json',root/'VALIDATION_FREEZE.json',args.output)
    print(json.dumps({key:result[key] for key in ('analysis','trajectory_count','sensitivity_totals',
        'prospective_formula_retention_under_posthoc_assumption','prospective_formula_utility_under_posthoc_assumption',
        'qualitative_retention_or_utility_conclusion_changed','new_native_or_provider_queries')},indent=2))
if __name__=='__main__':main()

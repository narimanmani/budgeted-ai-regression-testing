"""Pure qualification/reference separation and finite-bank stability checks."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
from experiment.development_v8.audits.audit_acquisition import read, sha, need

def compare(qualification,reference):
    need(qualification['audit_passed'] is True and reference['audit_passed'] is True,'Complete independent raw audits required')
    need(qualification['acquisition_role']=='qualification' and reference['acquisition_role']=='reference','Acquisition roles differ')
    for key in ('application_id','cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256'):
        need(qualification[key]==reference[key],'Reference uses another native cohort/prompt/input scope')
    old=qualification['all_scientific_query_details'];new=reference['all_scientific_query_details']
    for key in ('request_id','provider_request_id','raw_receipt_sha256'):
        need(not {row[key] for row in old}.intersection(row[key] for row in new),'Qualification evidence reused in reference acquisition: '+key)
    grouped=defaultdict(list)
    for row in new:grouped[(row['state_id'],row['task_id'])].append(row)
    need(all(sorted(row['pass'] for row in values)==[1,2] for values in grouped.values()),'Reference state/task cells lack two distinct passes')
    cells=[{'state_id':state,'task_id':task,'observed_primary_values':[row['primary_pass'] for row in sorted(values,key=lambda row:row['pass'])],
        'stable':len({row['primary_pass'] for row in values})==1} for (state,task),values in sorted(grouped.items())]
    reference_values={(row['state_id'],row['task_id'],row['pass']):row['primary_pass'] for row in new}
    differences=[{'state_id':row['state_id'],'task_id':row['task_id'],'pass':row['pass'],
        'qualification_primary':row['primary_pass'],'reference_primary':reference_values[(row['state_id'],row['task_id'],row['pass'])]}
        for row in old if row['primary_pass']!=reference_values[(row['state_id'],row['task_id'],row['pass'])]]
    return {'independent_receipt_ids_verified':True,'qualification_queries':len(old),'reference_queries':len(new),
        'reference_state_task_cells':len(cells),'stable_reference_cells':sum(row['stable'] for row in cells),
        'unstable_reference_cells':[row for row in cells if not row['stable']],
        'qualification_reference_primary_disagreements':differences,'reference_cells':cells,
        'population_stability_claimed':False,'new_native_or_model_calls':0}

def main():
    parser=argparse.ArgumentParser()
    for key in ('qualification-audit','reference-audit','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();qualification=read(args.qualification_audit);reference=read(args.reference_audit)
    result={'at_utc':datetime.now(timezone.utc).isoformat(),'application_id':reference['application_id'],
        **compare(qualification,reference),'qualification_audit_sha256':sha(args.qualification_audit),
        'reference_audit_sha256':sha(args.reference_audit),'code_sha256':sha(Path(__file__))}
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('independent_receipt_ids_verified','reference_state_task_cells','stable_reference_cells','qualification_reference_primary_disagreements')},indent=2))

if __name__=='__main__':main()

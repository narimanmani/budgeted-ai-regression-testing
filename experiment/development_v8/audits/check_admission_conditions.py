"""Rebuild frozen truth requirements from a completed independent raw audit."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
from experiment.development_v8.audits.audit_acquisition import read, sha, need

def conditions(audit,spec):
    need(audit.get('audit_passed') is True,'Completed independent raw audit required')
    observations=audit['all_scientific_query_details']
    indexed={(row['state_id'],row['task_id'],row['pass']):row['primary_pass'] for row in observations}
    need(len(indexed)==len(observations),'Duplicate state/task/pass in audited observations')
    required=[]
    for task in spec['task_ids']:
        for repeat in (1,2):required.append(('HEALTHY',task,repeat,True))
    for state in ('A_BAD','B_BAD'):
        for repeat in (1,2):
            required.append((state,spec['qualification_witnesses'][state],repeat,False))
            required.extend((state,task,repeat,True) for task in spec['unaffected_controls'])
    need(all((state,task,repeat) in indexed for state,task,repeat,_ in required),'Missing required witness/control/healthy observation')
    rows=[{'state_id':state,'task_id':task,'pass':repeat,'expected_primary':expected,
        'actual_primary':indexed[state,task,repeat]} for state,task,repeat,expected in required]
    failures=[row for row in rows if row['actual_primary']!=row['expected_primary']]
    need(audit['admission_passed']==(not failures),'Saved admission outcome differs from independently rebuilt truth requirements')
    return {'passed':not failures,'required_conditions':len(rows),'satisfied_conditions':len(rows)-len(failures),
        'violated_conditions':failures,'all_required_conditions':rows}

def main():
    parser=argparse.ArgumentParser()
    for key in ('audit','cohort','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();audit=read(args.audit);spec=args.cohort/'qualification.json'
    result={'at_utc':datetime.now(timezone.utc).isoformat(),'application_id':audit['application_id'],
        'cohort_id':audit['cohort_id'],'prompt_id':audit['prompt_candidate_id'],
        'source_audit_sha256':sha(args.audit),'qualification_spec_sha256':sha(spec),
        'new_native_or_model_calls':0,**conditions(audit,read(spec)),'code_sha256':sha(Path(__file__))}
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('passed','required_conditions','satisfied_conditions')},indent=2))

if __name__=='__main__':main()

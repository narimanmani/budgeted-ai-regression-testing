"""Choose only from complete predeclared development frames; no native work."""
from pathlib import Path
from datetime import datetime, timezone
import json
from experiment.development_v8.control import read, sha, write_new
from experiment.development_v8.protocol.gates import gate_saved_acquisition, select_development_candidate

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'experiment/runs/development_v8_20261101'

def main():
    freeze=read(RUN/'DEVELOPMENT_FREEZE.json')
    for name,expected in freeze['files_sha256'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Pre-answer development/source closure changed')
    ledger=[json.loads(s) for s in (RUN/'native_reservations.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    if any(row['metadata']['phase'] not in ('development','setup_probe') for row in ledger):
        raise RuntimeError('Development selection must precede all fresh validation answers and policy inputs')
    selections={};evidence={}
    for app in ('openwebui','dify'):
        cohort=HERE/'workloads/development'/app;qual=read(cohort/'qualification.json');results={};evidence[app]={}
        for candidate in ('P0','P1'):
            stage=RUN/f'development-{app}-{candidate}'
            completion=read(stage/'DRIVER_COMPLETION.json')
            if completion['execution_completed'] is not True:raise RuntimeError('Both development candidate executions must complete')
            input_path=RUN/'input_freezes'/f'development_{app}_{candidate}.json';inputs=read(input_path)
            audit_path=RUN/'audits'/f'INDEPENDENT_DEVELOPMENT_{app.upper()}_{candidate}.json'
            audit=read(audit_path)
            if audit.get('audit_passed') is not True:raise RuntimeError('Complete source/context/model/cost provenance must be independently verified')
            result=gate_saved_acquisition(stage/'meter',application_id=app,cohort_id='development',prompt_id=candidate,
                prompt_text_sha256=inputs['prompt_text_sha256'],input_freeze_sha256=sha(input_path),mode='development',
                task_ids=qual['task_ids'],contract_document=read(cohort/'contracts.json'),
                witnesses=qual['qualification_witnesses'],controls={s:qual['unaffected_controls'] for s in ('A_BAD','B_BAD')},
                bad_subsets=qual['qualification_subsets'])
            original=read(stage/'ADMISSION_GATE.json')
            if result!=original:raise RuntimeError('Independent saved-data gate differs from the retained original gate')
            results[candidate]=result
            evidence[app][candidate]={'admission_gate_sha256':sha(stage/'ADMISSION_GATE.json'),
                'independent_audit_sha256':sha(audit_path),'driver_completion_sha256':sha(stage/'DRIVER_COMPLETION.json'),
                'passed':result['passed'],'healthy_primary_passes':result['healthy_primary_passes'],'healthy_outputs':16}
        selections[app]=select_development_candidate(results,application_id=app,cohort_id='development')
    ready=all(value['selected_prompt_id'] for value in selections.values())
    write_new(RUN/'DEVELOPMENT_SELECTION.json',{
        'selected_at_utc':datetime.now(timezone.utc).isoformat(),
        'status':'READY_TO_FREEZE_FRESH_VALIDATION' if ready else 'STOP_NO_ELIGIBLE_DEVELOPMENT_CONFIGURATION',
        'development_freeze_sha256':sha(RUN/'DEVELOPMENT_FREEZE.json'),
        'selection_rule':'First eligible P0,P1 after both full candidate frames; no maximization of fault count or guidance benefit',
        'selection_by_application':selections,'candidate_evidence':evidence,
        'selected_prompt_by_application':{app:result['selected_prompt_id'] for app,result in selections.items()},
        'fresh_validation_answers_seen':0,'guide_or_policy_results_seen':0,
        'all_prior_failed_cohorts_and_candidate_results_retained':True,
        'new_native_or_model_queries':0})
    print(json.dumps({'ready_to_freeze_validation':ready,'selected_prompt_by_application':{a:r['selected_prompt_id'] for a,r in selections.items()}}))

if __name__=='__main__':main()

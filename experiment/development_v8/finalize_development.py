"""Close the disclosed extension using development evidence only."""
from datetime import datetime, timezone
import json
from experiment.development_v8.round2 import ROOT, HERE, RUN
from experiment.development_v8.control import read, sha, write_new
from experiment.development_v8.protocol.gates import gate_saved_acquisition

def main():
    old=read(RUN/'DEVELOPMENT_SELECTION.json')
    if old['status']!='STOP_NO_ELIGIBLE_DEVELOPMENT_CONFIGURATION':raise RuntimeError('Retain the actual Round1 failure')
    ledger=[json.loads(s) for s in (RUN/'native_reservations.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    if any(r['metadata']['phase'] not in ('development','setup_probe') for r in ledger):raise RuntimeError('Validation/policy outcomes must remain unobserved')
    directory=RUN/'development-dify-P2';q=read(HERE/'workloads/development/dify/qualification.json')
    inputs=RUN/'development_round2/INPUT_FREEZE.json';audit_path=RUN/'audits/INDEPENDENT_DEVELOPMENT_DIFY_P2.json'
    audit=read(audit_path)
    if (audit.get('audit_passed') is not True or audit.get('prompt_candidate_id')!='P2'
        or audit.get('input_freeze_sha256')!=sha(inputs)):raise RuntimeError('Exact P2 native/source/model/cost provenance required')
    result=gate_saved_acquisition(directory/'meter',application_id='dify',cohort_id='development',prompt_id='P2',
        prompt_text_sha256=read(inputs)['prompt_text_sha256'],input_freeze_sha256=sha(inputs),mode='development',
        task_ids=q['task_ids'],contract_document=read(HERE/'workloads/development/dify/contracts.json'),
        witnesses=q['qualification_witnesses'],controls={s:q['unaffected_controls'] for s in ('A_BAD','B_BAD')},
        bad_subsets=q['qualification_subsets'])
    if result!=read(directory/'ADMISSION_GATE.json'):raise RuntimeError('Saved P2 admission changed')
    ready=result['passed'] and old['selected_prompt_by_application']['openwebui']=='P0'
    write_new(RUN/'DEVELOPMENT_FINAL_SELECTION.json',{
        'at_utc':datetime.now(timezone.utc).isoformat(),
        'status':'READY_TO_FREEZE_FRESH_VALIDATION' if ready else 'STOP_NO_ELIGIBLE_DEVELOPMENT_CONFIGURATION',
        'selected_prompt_by_application':{'openwebui':'P0','dify':'P2' if result['passed'] else None},
        'round1_status':old['status'],'round1_closed_decision_sha256':sha(RUN/'DEVELOPMENT_SELECTION.json'),
        'round2_registration_sha256':sha(RUN/'development_round2/ROUND2_FREEZE.json'),
        'round2_admission_sha256':sha(directory/'ADMISSION_GATE.json'),'round2_independent_audit_sha256':sha(audit_path),
        'selection_rule':'Retain eligible OpenWebUI P0 from Round1; accept the sole predeclared Dify P2 extension only when all unchanged admission conditions pass',
        'adaptive_development_extension_disclosed':True,'original_two_candidate_protocol_pass_claimed':False,
        'validation_answers_or_policy_results_used':False,'all_failed_candidates_retained':True,
        'same_unqueried_validation_bytes_retained':True,'new_native_or_model_queries':0})
    print(json.dumps({'ready_for_validation_freeze':ready,'selected':{'openwebui':'P0','dify':'P2' if ready else None}}))

if __name__=='__main__':main()

"""Trace original label bytes through saved native index/context/generation.

This locates the first observed mismatch. It does not isolate a causal model
mechanism and performs no source correction, experiment retry or native call.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import re
from experiment.development_v8.audits.audit_acquisition import read, sha, need, choose_provider_events
from experiment.development_v8.audits.audit_native_dify import native_context

def explain(run,cohort,audit_path):
    run=Path(run).resolve();cohort=Path(cohort).resolve();audit=read(audit_path)
    need(audit['audit_passed'] is True and audit['application_id']=='dify','Complete independent native Dify audit required')
    source_rows={row['logical_id']:row for row in read(cohort/'source_manifest.json')['sources']}
    contracts={row['id']:row for row in read(cohort/'contracts.json')['contracts']}
    qualification=read(cohort/'qualification.json');selected=qualification['qualification_witnesses']
    controls=qualification['unaffected_controls']
    records=audit['all_scientific_query_details']
    ids={row['provider_request_id'] for row in records}
    provider=choose_provider_events(run/'provider/requests.jsonl',ids);chains=[]
    for observation in records:
        task=observation['task_id'];state=observation['state_id'];spec=contracts[task]
        source=source_rows[spec['required_logical_source_id']];file=cohort/source['file']
        need(sha(file)==source['sha256'],'Original source bytes changed')
        original=file.read_bytes().decode(source['encoding'],errors='strict')
        match=re.search(r'Record\s+'+re.escape(task)+r'\s+access\s+label\s+\[([^\]]*)\]',original)
        need(match is not None,'Original matching record label missing')
        label=match.group(1);raw=read(observation['raw_receipt_path'])
        need(sha(observation['raw_receipt_path'])==observation['raw_receipt_sha256'],'Audited raw receipt changed')
        native=raw['native_output'];binding=next(b for b in native['source_bindings'] if b['logical_id']==source['logical_id'])
        index_contents=[segment['content'] for segment in binding['segments']]
        returned=[context for context in native['returned_contexts'] if context['document_id']==binding['native_document_id']]
        returned_contents=[context['content'] for context in returned]
        model=provider[observation['provider_request_id']];context=native_context('dify',model,native)
        in_index=any(label in text for text in index_contents)
        in_returned=any(label in text for text in returned_contents)
        in_prompt=label in context;answer=native['answer']
        diagnosis='Contract passes'
        if not observation['primary_pass']:
            if not in_index:diagnosis='Original label differs/absent in native indexed segments'
            elif not in_returned:diagnosis='Indexed original label absent from native returned contexts'
            elif not in_prompt:diagnosis='Returned original label absent from actual model context'
            elif label in answer:diagnosis='Generated output contains the correct label with additional characters/text'
            else:diagnosis='Generated output differs despite original label present in actual model context'
        role=[]
        if task in selected.values():role.append('predeclared witness')
        if task in controls:role.append('predeclared unaffected control')
        chains.append({'state_id':state,'task_id':task,'pass':observation['pass'],'roles':role,
            'source_file_path':str(file),'source_file_sha256':sha(file),'source_encoding':source['encoding'],
            'original_decoded_source':original,'original_contract_label':label,
            'native_document_id':binding['native_document_id'],'native_workspace_id':binding['workspace_id'],
            'native_original_sha256':binding['original_sha256'],'native_indexed_segment_contents':index_contents,
            'native_indexed_record_id_present':any(task in text for text in index_contents),
            'original_label_present_in_native_indexed_segments':in_index,
            'actual_native_returned_segment_contents':returned_contents,
            'original_label_present_in_native_returned_contexts':in_returned,
            'original_label_present_in_actual_model_context':in_prompt,
            'generated_answer':answer,'exact_contract_pass':observation['primary_pass'],
            'earliest_observed_mismatch':diagnosis,'raw_receipt_path':observation['raw_receipt_path'],
            'raw_receipt_sha256':observation['raw_receipt_sha256'],
            'actual_provider_request_id':model['request_id'],'actual_upstream_request_sha256':model['upstream_request_sha256']})
    failures=[row for row in chains if row['state_id']=='HEALTHY' and not row['exact_contract_pass']]
    return {'at_utc':datetime.now(timezone.utc).isoformat(),'application_id':'dify',
        'cohort_id':audit['cohort_id'],'prompt_id':audit['prompt_candidate_id'],
        'complete_independent_audit_path':str(Path(audit_path).resolve()),'complete_independent_audit_sha256':sha(audit_path),
        'new_native_or_model_calls':0,'original_inputs_answers_contracts_or_prompts_changed':False,
        'scientific_questions':len(chains),'admission_passed':audit['admission_passed'],
        'failed_healthy_observations':failures,
        'all_failed_healthy_original_labels_survived_index_retrieval_and_prompt':all(
            row['original_label_present_in_native_indexed_segments'] and row['original_label_present_in_native_returned_contexts']
            and row['original_label_present_in_actual_model_context'] for row in failures),
        'interpretation':'Each row records the earliest visible mismatch between source, native index, returned context, actual model prompt and generated contract output. A generated mismatch with an intact label does not isolate a particular causal language-model mechanism.',
        'all_source_to_answer_chains':chains,'explanation_source_sha256':sha(Path(__file__))}

def main():
    parser=argparse.ArgumentParser()
    for name in ('run','cohort','audit','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=explain(args.run,args.cohort,args.audit)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('admission_passed','scientific_questions','all_failed_healthy_original_labels_survived_index_retrieval_and_prompt')},indent=2))

if __name__=='__main__':main()

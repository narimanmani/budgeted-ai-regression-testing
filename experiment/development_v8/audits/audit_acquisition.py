"""Read-only completed-cohort audit. No application, provider or model dispatch.

Only provider events named by this acquisition's completed root receipts are
parsed, so concurrently running acquisitions do not become audit inputs.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
import re

from experiment.validation_v7.execution.source_channels import CanonicalContracts

SCOPE=('cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256')
STATES=('HEALTHY','A_BAD','B_BAD')

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def rows(path):return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(condition,message):
    if not condition:raise ValueError(message)

def choose_provider_events(log,request_ids):
    """Do not parse unrelated model outputs while another cohort is active."""
    result={}
    with Path(log).open(encoding='utf-8-sig') as stream:
        for line in stream:
            match=re.match(r'^\{"request_id":\s*"([^"]+)"',line)
            if not match or match.group(1) not in request_ids:continue
            value=json.loads(line);ident=value['request_id']
            need(ident not in result,'Duplicate provider receipt')
            result[ident]=value
    need(set(result)==set(request_ids),'A completed provider receipt is missing')
    return result

def prompt_context(application,event,native):
    contents=[m['content'] for m in event['upstream_request']['messages'] if isinstance(m.get('content'),str)]
    matches=[m for text in contents for m in re.finditer(r'<context>(.*?)</context>',text,re.S)]
    need(len(matches)==1,'Actual generation prompt has no unique native context expansion')
    context=matches[0].group(1)
    if application=='dify':
        expected='\n'.join(row['content'] for row in native['returned_contexts'])
        need(context.strip('\n')==expected,'Dify returned contexts differ from actual native prompt')
    else:
        need(all(row['document'] in context for row in native['returned_contexts']),
             'An OpenWebUI returned context is absent from the actual generation prompt')
    return context

def model_check(event,backend_sha):
    upstream=event['upstream_request'];actual=event['upstream_actual_response'];verbose=actual['__verbose'];usage=actual['usage']
    need(event['backend_receipt_sha256']==backend_sha,'Generation backend provenance differs')
    need(event['http_status']==event['upstream_http_status']==200 and event['llamacpp_response_validation_passed'] is True,'Invalid actual model response')
    need(upstream['model']=='tosem-qwen2.5-7b-q4' and upstream['temperature']==0 and upstream['max_tokens']==96,'Scientific model parameters differ')
    need(verbose['generation_settings']['temperature']==0 and verbose['generation_settings']['n_predict']==96,'Actual backend generation parameters differ')
    need(upstream['cache_prompt'] is False and actual['timings']['cache_n']==0 and usage['prompt_tokens_details']['cached_tokens']==0,'Cross-request model prompt cache reused')
    need(event['bridge_input_truncation'] is False and verbose['truncated'] is False,'Input was truncated')
    need(usage['prompt_tokens']+usage['completion_tokens']<=4096 and usage['completion_tokens']<=96,'Actual context/output limit exceeded')
    return usage

def join_check(receipt,events):
    need(receipt.get('dispatch_safe_to_continue') is True and receipt['provider_join']['joined'] is True,'Unreconciled root operation')
    linked=[events[ident] for ident in receipt['provider_join']['provider_request_ids']]
    need(all(row['allocation_id']==receipt['allocation_id'] for row in linked),'Provider event belongs to another allocation')
    chat=[row for row in linked if row['path']=='/v1/chat/completions'];embed=[row for row in linked if row['path']=='/v1/embeddings']
    need(len(chat)==receipt['provider_join']['chat_boundary_attempts'] and len(embed)==receipt['provider_join']['embedding_boundary_attempts'],'Root provider boundary counts differ')
    need(math.isclose(sum(row.get('generate_gpu_allocation_seconds_including_failure',0) for row in chat),receipt['provider_join']['gpu_allocation_seconds'],abs_tol=1e-6),'GPU allocation join differs')
    need(math.isclose(sum(row.get('embedding_cpu_seconds',0) for row in embed),receipt['provider_join']['embedding_cpu_seconds_recorded'],abs_tol=1e-6),'Embedding CPU join differs')
    return chat,embed

def audit_sources(application,state,bindings,source_rows):
    need(len(bindings)==8 and {b['logical_id'] for b in bindings}==set(source_rows),'Native source catalog differs from frozen eight documents')
    ids=[b.get('native_file_id',b.get('native_document_id')) for b in bindings]
    need(all(ids) and len(set(ids))==8,'Actual native source IDs are missing or duplicated')
    spaces={b['workspace_id'] for b in bindings};need(len(spaces)==1,'Source bindings span multiple workspaces')
    proofs=set();segments=0
    for binding in bindings:
        original=source_rows[binding['logical_id']]
        need(binding['state_id']==state and binding['indexed'] is True,'Native binding not indexed in the requested state')
        need(binding['original_sha256']==original['sha256'] and binding['version']==original['version'],'Original native upload bytes/version differ')
        path=Path(binding['source_verification_path']);need(sha(path)==binding['source_verification_sha256'],'Native source-verification receipt changed')
        proof=read(path);count=290 if application=='openwebui' else 2459
        detail=proof if application=='openwebui' else proof['verification']
        need(detail['checked']==count and detail['mismatches']==[],'Native production Python source verification failed')
        need(proof.get('state',proof.get('state_id'))==state,'Native source verification belongs to another state')
        manifest=Path(binding['source_manifest_path']);need(sha(manifest)==binding['source_manifest_sha256'],'Production source manifest changed')
        cohort=Path(binding['cohort_source_manifest_path']);need(sha(cohort)==binding['cohort_source_manifest_sha256'],'Original cohort manifest changed')
        if application=='openwebui':
            spec=read(manifest);need(len(spec['expected_production_blobs'])==count,'Source production scope count differs')
            need(proof['fixed_revision']==spec['fixed_revision'],'Native image revision differs')
            over=spec['overrides'].get(state);need(proof['permitted_override_paths']==([over['native_path']] if over else []),'Unexpected production source override')
        else:
            need(all(row['indexing_status']=='completed' for row in binding['indexing_status']),'Native document indexing did not complete')
            segments+=len(binding['segments'])
        proofs.add((str(path),sha(path)))
    need(len(proofs)==1,'A state has inconsistent production source proof references')
    return {'state':state,'verified_production_python_files':290 if application=='openwebui' else 2459,
        'actual_native_documents':8,'workspace_id':next(iter(spaces)),'production_source_receipts':list(proofs),
        'native_segments':segments if application=='dify' else None}

def audit(run,acquisition,cohort,config_path):
    run=Path(run).resolve();acquisition=Path(acquisition).resolve();cohort=Path(cohort).resolve()
    meter=acquisition/'meter' if (acquisition/'meter/REFERENCE_COMPLETION.json').exists() else acquisition
    summary=read(meter/'REFERENCE_COMPLETION.json')
    need(summary['error'] is None and summary['outputs']==summary['planned_outputs'] and summary['outputs'] in (32,48),'A complete declared acquisition is required before auditing generated answers')
    driver=read(acquisition/'DRIVER_COMPLETION.json')
    need(driver['result']==summary,'Driver completion and actual acquisition summary differ')
    application=summary['application_id'];phase=summary['phase'];config=read(config_path)
    need(application in ('openwebui','dify') and phase in ('development','qualification','reference'),'Unknown application/acquisition role')
    scope={key:summary[key] for key in SCOPE};freeze=read(acquisition/'ACQUISITION_SOURCE_FREEZE.json')
    need({key:freeze[key] for key in SCOPE}==scope,'Acquisition source freeze has a different cohort/prompt scope')
    need(sha(config['input_freeze_file'])==scope['input_freeze_sha256'] and config['input_freeze_sha256']==scope['input_freeze_sha256'],'Native input-freeze hash differs')
    need(config['cohort_id']==scope['cohort_id'] and config['prompt_id']==scope['prompt_candidate_id'] and hashlib.sha256(config['prompt_text'].encode()).hexdigest()==scope['prompt_text_sha256'],'Actual native prompt/cohort configuration differs')
    need(Path(config['cohort_dir']).resolve()==cohort,'Audited cohort differs from native configuration')
    changed=[name for name,value in freeze['files_sha256'].items() if sha(name)!=value]
    need(not changed,'An acquisition source/input file changed')
    specs={row['id']:row for row in read(cohort/'contracts.json')['contracts']};checker=CanonicalContracts(read(cohort/'contracts.json'))
    task_rows={row['id']:row for row in read(cohort/'tasks.json')['tasks']};source_rows={row['logical_id']:row for row in read(cohort/'source_manifest.json')['sources']}
    need(len(specs)==len(task_rows)==len(source_rows)==8 and set(specs)==set(task_rows),'Frozen eight-task/source/contract frame differs')
    labels={}
    for task,spec in specs.items():
        source=source_rows[spec['required_logical_source_id']];file=cohort/source['file']
        need(sha(file)==source['sha256'],'Original source bytes changed')
        decoded=file.read_bytes().decode(source['encoding'],errors='strict')
        match=re.search(r'Record\s+'+re.escape(task)+r'\s+access\s+label\s+\[([^\]]*)\]',decoded)
        need(match is not None and match.group(1) in spec['accepted_values'],'Contract does not follow the original matching record bytes')
        labels[task]=match.group(1)
    index=rows(meter/'sealed/reference_outputs.jsonl');need(len(index)==summary['outputs'],'Missing or extra saved query results')
    raw_all=[read(path) for path in sorted((meter/'raw').glob('*.json'))]
    raw_map={row['request_id']:row for row in raw_all};need(len(raw_map)==len(raw_all),'Duplicated native request ID')
    setup_paths=[meter/'SETUP.json',*sorted((meter/'setup_steps').glob('*.json'))]
    setup=[read(path) for path in setup_paths if path.exists()]
    all_operations=[*setup,*raw_all];receipts=[row['root_meter_receipt'] for row in all_operations]
    wanted=[ident for receipt in receipts for ident in receipt['provider_join']['provider_request_ids']]
    need(len(set(wanted))==len(wanted),'Provider event appears in more than one acquisition operation')
    events=choose_provider_events(run/'provider/requests.jsonl',set(wanted))
    root_ops={row['allocation_id']:row for row in rows(run/'operation_index.jsonl')}
    for receipt in receipts:
        path=Path(receipt['receipt_path']);entry=root_ops[receipt['allocation_id']]
        need(Path(entry['path']).resolve()==path.resolve() and sha(path)==entry['sha256'] and read(path)==receipt,'Sealed root operation differs')
        chat,embed=join_check(receipt,events)
        if receipt['native_query_units_reserved']==0:need(not chat,'Metadata-only setup caused generation')
    backend_sha=read(run/'CAMPAIGN_AUTH.json')['backend_receipt_sha256']
    checked=[];source_checks={};seen=set();conversations=[];http_logs={}
    ledger={row['request_id']:row for row in rows(run/'native_reservations.jsonl')}
    for entry in index:
        path=Path(entry['receipt_path']);need(sha(path)==entry['receipt_sha256'],'Bound raw query receipt changed')
        raw=raw_map[entry['request_id']];need(read(path)==raw,'Raw query index mismatch')
        state=raw['state_id'];task=raw['task_id'];native=raw['native_output'];receipt=raw['root_meter_receipt']
        cell=(state,task,entry['repetition']);need(cell not in seen,'Duplicate state/task/pass');seen.add(cell)
        need(raw['phase']==phase and raw['application_id']==application,'Saved query role/application differs')
        need(all(raw[key]==native[key]==entry[key] for key in ('request_id','state_id','task_id',*SCOPE)),'Native/wrapper/index scope or identity differs')
        need(receipt['native_reservation']==ledger[raw['request_id']] and receipt['native_query_units_reserved']==1,'Query not bound to one prior native reservation')
        metadata=receipt['native_reservation']['metadata']
        need(all(metadata[key]==raw[key] for key in ('application_id','request_id','state_id','task_id','phase','trajectory_id',*SCOPE)),'Reserved scientific role/cohort differs')
        original=read(native['receipt_path']);need(sha(native['receipt_path'])==native['receipt_sha256'],'Native original receipt changed')
        need(all(native[key]==value for key,value in original.items()),'Native payload changed in root wrapper')
        need(native['valid_native_response'] is True and native['completed'] is True,'Native completion invalid')
        need(native['source_bindings']==raw['native_output']['source_bindings'],'Actual source snapshot differs')
        if state not in source_checks:source_checks[state]=audit_sources(application,state,native['source_bindings'],source_rows)
        else:need(native['source_bindings']==source_checks[state]['bindings'],'A state source catalog changed during acquisition')
        source_checks[state]['bindings']=native['source_bindings']
        need(native['workspace_id']==source_checks[state]['workspace_id'],'Query workspace differs from its native source catalog')
        chat,embed=join_check(receipt,events);need(len(chat)==1,'Scientific query must have exactly one actual generation')
        event=chat[0];usage=model_check(event,backend_sha);context=prompt_context(application,event,native)
        need(any(task_rows[task]['question'] in message.get('content','') for message in event['upstream_request']['messages']),'Actual model prompt omits the frozen question')
        factual=checker.check(task,native,bindings=native['source_bindings'],state=state,reference=True)
        need(factual==entry['reference_check'],'Independent primary/source checking differs from saved acquisition')
        config_receipt=Path(native['native_configuration_receipt_path']);need(sha(config_receipt)==native['native_configuration_receipt_sha256'],'Native model/RAG configuration receipt changed')
        actual_config=read(config_receipt)
        if application=='openwebui':
            need(actual_config['rag']['TOP_K']==8 and actual_config['rag']['RAG_TEMPLATE']==(config['prompt_text']+'\n<context>\n{{CONTEXT}}\n</context>').replace('\n',' '),'Actual OpenWebUI prompt/retrieval configuration differs')
            native_dir=config_receipt.parents[2]
            if state not in http_logs:http_logs[state]=[read(path) for path in (native_dir/'http'/state).glob('*.json')]
            calls=[row for row in http_logs[state] if row['allocation_id']==raw['request_id'] and row['path']=='/api/chat/completions' and isinstance(row.get('request'),dict)]
            need(len(calls)==1 and calls[0]['request']['session_id']==raw['request_id'] and calls[0]['request']['id']==raw['request_id'],'Native OpenWebUI request/session not fresh and reserved')
        else:
            actual=actual_config['app_configuration_readback']['model_config']
            need(actual['pre_prompt']==config['prompt_text'] and actual['model']['completion_params']['max_tokens']==96,'Actual Dify generic prompt/model configuration differs')
            conversations.append(native['native_conversation_id'])
        checked.append({'request_id':raw['request_id'],'state_id':state,'task_id':task,'pass':entry['repetition'],
            'primary_pass':factual['primary_pass'],'source_metadata_pass':factual['source_metadata_pass'],
            'answer':native['answer'],'original_expected_label':labels[task],
            'original_label_present_in_actual_model_context':labels[task] in context,
            'all_returned_contexts_reached_model':True,'actual_prompt_tokens':usage['prompt_tokens'],
            'actual_completion_tokens':usage['completion_tokens'],'raw_receipt_path':str(path),
            'raw_receipt_sha256':sha(path),'provider_request_id':event['request_id']})
    qualification=read(cohort/'qualification.json')
    selected={state:(qualification['qualification_subsets'].get(state,list(specs)) if phase=='qualification' else list(specs)) for state in STATES}
    required={(state,task,repeat) for state,task_ids in selected.items() for task in task_ids for repeat in (1,2)}
    need(seen==required,'Actual state/task/pass frame differs from the declared acquisition')
    need(len({value['workspace_id'] for value in source_checks.values()})==3,'Native states do not have separate indexed workspaces')
    if application=='dify':need(len(set(conversations))==len(index),'Dify conversation context was reused')
    own={key:0. for key in ('native_query_units','chat_boundaries','embedding_boundaries','gpu_allocation_seconds','embedding_cpu_seconds')}
    for receipt in receipts:
        joined=receipt['provider_join'];own['native_query_units']+=receipt['native_query_units_reserved'];own['chat_boundaries']+=joined['chat_boundary_attempts'];own['embedding_boundaries']+=joined['embedding_boundary_attempts'];own['gpu_allocation_seconds']+=joined['gpu_allocation_seconds'];own['embedding_cpu_seconds']+=joined['embedding_cpu_seconds_recorded']
    total=summary['physical_usage']
    for key,saved in (('native_query_units','native_query_units'),('chat_boundaries','provider_chat_boundaries'),('embedding_boundaries','embedding_boundaries'),('gpu_allocation_seconds','gpu_allocation_seconds'),('embedding_cpu_seconds','embedding_cpu_seconds')):
        need(math.isclose(own[key],total[saved],abs_tol=1e-6),'Acquisition physical usage does not reconcile: '+key)
    failures=[row for row in checked if row['state_id']=='HEALTHY' and not row['primary_pass']]
    gate=read(acquisition/'ADMISSION_GATE.json')
    return {'audited_at_utc':datetime.now(timezone.utc).isoformat(),'audit_passed':True,'application_id':application,
        'acquisition_role':phase,**scope,'new_native_or_model_calls':0,'original_evidence_modified':False,
        'complete_scientific_questions':len(index),'admission_passed':gate['passed'],
        'all_scientific_generations_fixed_temperature0_limit96_untruncated_uncached':True,
        'all_native_contexts_reached_actual_model_prompt':True,'frozen_source_input_mismatches':changed,
        'frozen_source_input_files_checked':len(freeze['files_sha256']),
        'actual_prompt_token_range':[min(row['actual_prompt_tokens'] for row in checked),max(row['actual_prompt_tokens'] for row in checked)],
        'actual_completion_token_range':[min(row['actual_completion_tokens'] for row in checked),max(row['actual_completion_tokens'] for row in checked)],
        'counts_by_state':{state:{'questions':sum(row['state_id']==state for row in checked),
            'primary_passes':sum(row['state_id']==state and row['primary_pass'] for row in checked),
            'source_passes':sum(row['state_id']==state and row['source_metadata_pass'] for row in checked)} for state in STATES},
        'failed_healthy_observations':failures,
        'source_verification':{state:{key:value for key,value in proof.items() if key!='bindings'} for state,proof in source_checks.items()},
        'physical_usage':own,'root_operations_joined':len(receipts),'all_scientific_query_details':checked,
        'acquisition_completion_sha256':sha(meter/'REFERENCE_COMPLETION.json'),'audit_code_sha256':sha(Path(__file__))}

def main():
    parser=argparse.ArgumentParser()
    for field in ('run','acquisition','cohort','config','output'):parser.add_argument('--'+field,type=Path,required=True)
    args=parser.parse_args();result=audit(args.run,args.acquisition,args.cohort,args.config)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('audit_passed','application_id','complete_scientific_questions','admission_passed','counts_by_state','physical_usage')},indent=2))

if __name__=='__main__':main()

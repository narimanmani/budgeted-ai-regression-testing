"""Attributed finalized AL metering copy including complete-boundary and incident quarantine rules.
No AL file is imported or edited at runtime; adjacent provenance records its exact origin hash.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib,json,math,os,time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

def utc():return datetime.now(timezone.utc).isoformat()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def append(path,value):
    with Path(path).open('a',encoding='utf-8') as stream:stream.write(json.dumps(value,ensure_ascii=True)+'\n');stream.flush();os.fsync(stream.fileno())

def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,ensure_ascii=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def atomic(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    payload=json.dumps(value,indent=2,ensure_ascii=True)+'\n'
    started=time.monotonic();retries=0
    while True:
        try:
            with temporary.open('w',encoding='utf-8') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
            return {'permission_retries':retries,'wall_seconds':time.monotonic()-started,'scope':'File I/O only; no native/model operation repeated'}
        except PermissionError:
            retries+=1
            if time.monotonic()-started>=1. or retries>=64:raise
            time.sleep(.02)

def rows(path):
    path=Path(path)
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()] if path.exists() else []

def study_incidents(output,provider_receipts):
    """Instrumentation/admission failures never become regression truth."""
    incidents=[]
    codes={'invalid_allocation','allocation_expired','allocation_changed','allocation_changed_after_queue',
           'missing_allocation','missing_allocation_identity','wrong_reference_phase','invalid_allocation_expiry',
           'wrong_phase','wrong_model','wrong_generation_backend','counter_persistence_pending','upstream_pending',
           'upstream_transport_pending','resource_cap_reached','allocation_cap_reached','gpu_time_cap_reached',
           'shared_gpu_cap_reached','invalid_allocation','unreserved_generation'}
    for row in provider_receipts:
        error=row.get('error') or {};kind=error.get('type') if isinstance(error,dict) else None
        if row.get('counter_persistence_error_stage') or kind in {'PermissionError','counter_persistence_pending'} or (row.get('counters') or {}).get('counter_persistence_failed'):
            incidents.append('study_counter_persistence_error')
        if row.get('upstream_work_pending') or row.get('actual_native_generation_not_independently_observed_on_transport_failure'):
            incidents.append('study_upstream_termination_unresolved')
        if kind in codes:incidents.append('study_provider_admission_or_routing:'+kind)
        if error or (type(row.get('http_status')) is int and row['http_status']>=400):
            incidents.append('study_provider_failure_requires_adjudication')
        if row.get('client_disconnected'):incidents.append('study_provider_transport_disconnected')
    if output is None or not isinstance(output,dict):incidents.append('study_adapter_result_unavailable')
    else:
        if output.get('adapter_exception'):incidents.append('study_native_transport_or_adapter_exception')
        for key in ['receipt','embedding_receipt']:
            receipt=output.get(key) or {}
            if receipt.get('transport_error'):incidents.append('study_native_transport_or_adapter_exception')
            if receipt.get('http_status') in {401,403}:incidents.append('study_native_credentials_rejected')
            if receipt.get('http_status') in {404,429}:incidents.append('study_native_route_or_rate_limit')
            if type(receipt.get('http_status')) is int and receipt['http_status']>=400 and receipt.get('native_started') is not True:
                incidents.append('study_native_error_without_admission_evidence')
        error=str((output.get('receipt') or {}).get('native_error') or (output.get('native_response') or {}).get('error') or '').casefold()
        if ('model' in error and any(word in error for word in ['not found','unknown','unavailable','not set'])) or 'api key' in error or 'allocation' in error:
            incidents.append('study_native_model_credentials_or_allocation_error')
    return sorted(set(incidents))

@contextmanager
def owner(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    write_new(path,{'pid':os.getpid(),'opened_at_utc':utc(),'role':'exclusive_native_reference_collector'})
    try:yield
    finally:path.unlink()

def provider_join(before,after,related,*,chat_cap=3,allow_chat=True,expected_backend_receipt=None,require_boundary_counters=False):
    """All boundary attempts count, including rejected/unreserved attempts."""
    generation=[x for x in related if x.get('path')=='/v1/chat/completions']
    numbered=[x['generation_request_number'] for x in generation if 'generation_request_number' in x]
    first=before['chat_requests_reserved'];last=after['chat_requests_reserved']
    joined=last>=first and sorted(numbered)==list(range(first+1,last+1)) and len(numbered)==len(set(numbered))
    embeddings=[x for x in related if x.get('path')=='/v1/embeddings']
    if require_boundary_counters:
        keys=[('reference_boundary_attempts_received',len(generation)+len(embeddings)),
              ('reference_chat_boundary_attempts_received',len(generation)),
              ('reference_embedding_boundary_attempts_received',len(embeddings))]
        for key,observed in keys:
            delta=after.get(key,0)-before.get(key,0)
            if type(delta) is not int or delta<0 or delta!=observed:joined=False
        boundary_numbers=[x.get('reference_boundary_attempt_number') for x in related]
        expected=list(range(before.get('reference_boundary_attempts_received',0)+1,after.get('reference_boundary_attempts_received',0)+1))
        if any(type(x) is not int for x in boundary_numbers) or sorted(x for x in boundary_numbers if type(x) is int)!=expected:
            joined=False
        started_delta=after.get('embedding_requests_started',0)-before.get('embedding_requests_started',0)
        completed_delta=after.get('embedding_requests_completed',0)-before.get('embedding_requests_completed',0)
        completed_rows=[x for x in embeddings if x.get('embedding_cpu_seconds') is not None]
        if not 0<=started_delta<=len(embeddings) or completed_delta!=len(completed_rows):joined=False
        if after.get('embedding_inputs_completed',0)-before.get('embedding_inputs_completed',0)!=sum(x.get('embedding_input_count',0) for x in completed_rows):joined=False
    if any(not x.get('finished_at_utc') for x in related):joined=False
    gpu=cpu=setup=0.
    for row in related:
        started=row.get('hf_generate_started') is True or row.get('llamacpp_http_started') is True
        if row.get('upstream_work_pending') or row.get('actual_native_generation_not_independently_observed_on_transport_failure'):
            joined=False
        if expected_backend_receipt is not None and started:
            if row.get('llamacpp_http_started') is not True or row.get('backend_receipt_sha256')!=expected_backend_receipt:
                joined=False
        if started and row.get('generate_gpu_allocation_seconds_including_failure') is None:joined=False
        for key in ['generate_gpu_allocation_seconds_including_failure','model_setup_gpu_allocation_seconds']:
            value=row.get(key,0.)
            if value is None or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                joined=False
            else:gpu+=value
        for key in ['embedding_cpu_seconds','embedding_setup_seconds']:
            value=row.get(key,0.)
            if value is None or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:joined=False
            elif key=='embedding_cpu_seconds':cpu+=value
            else:setup+=value
    return {'joined':joined,'chat_boundary_attempts':len(generation),'reserved_generation_attempts':last-first,
            'attempt_cap_exceeded':len(generation)>chat_cap or (not allow_chat and bool(generation)),
            'provider_request_ids':[r['request_id'] for r in related],
            'gpu_allocation_seconds':gpu if joined else None,
            'embedding_boundary_attempts':sum(r.get('path')=='/v1/embeddings' for r in related),
            'embedding_cpu_seconds_recorded':cpu,'embedding_setup_seconds_recorded':setup,
            'provider_cost_kind':'Serialized native upstream allocation wall including failures, not kernel-active time'}

class Provider:
    def __init__(self,auth,run):
        self.auth=auth;self.run=Path(run);self.state=Path(auth['provider_state_dir']).resolve()
        self.opener=build_opener(ProxyHandler({}))
        self.initial_log_count=len(rows(self.state/'requests.jsonl'))
        self.initial_counter=self.health()['counters']
        if self.initial_counter['chat_requests_reserved']!=0:raise RuntimeError('Reference provider phase must begin with no previously reserved generation units')

    def health(self):
        with self.opener.open(Request('http://127.0.0.1:33001/health'),timeout=10) as response:value=json.load(response)
        if value.get('phase')!=self.auth['provider_phase'] or value.get('public_model')!=self.auth['model_id']:
            raise RuntimeError('Provider phase/model does not match separate reference authorization')
        if value.get('backend_receipt_sha256')!=self.auth['backend_receipt_sha256'] or value.get('status')!='ok':
            raise RuntimeError('Physical backend provenance/readiness differs from root authorization')
        if value.get('boundary_attempt_counters_supported') is not True:
            raise RuntimeError('Provider must expose received-before-work boundary counters for complete receipt joins')
        if value.get('upstream_pending') or value['counters'].get('counter_persistence_failed'):
            raise RuntimeError('Unresolved provider work or counter persistence blocks collection')
        return value

    def budget(self):
        if (self.run/'ACCOUNTING_BLOCK.json').exists():raise RuntimeError('Unresolved reference accounting blocks any further dispatch')
        clock=read(self.run/'REFERENCE_CLOCK.json')
        elapsed=time.monotonic()-clock['started_monotonic']
        if elapsed<0:raise RuntimeError('Monotonic clock discontinuity; do not reset the phase')
        remaining=min(self.auth['wall_seconds_cap']-elapsed,self.auth['expires_at_epoch']-time.time())
        if remaining<=0:raise RuntimeError('Reference wall/authorization cap reached')
        health=self.health();counter=health['counters']
        gpu=counter.get('gpu_allocation_seconds_accounted')
        if not isinstance(gpu,(int,float)) or not math.isfinite(gpu) or gpu<0:raise RuntimeError('Provider GPU allocation is unknown')
        if gpu>=self.auth['phase_gpu_cap_seconds'] or gpu+self.auth['prior_shared_gpu_seconds']>=self.auth['shared_gpu_cap_seconds']:
            raise RuntimeError('Root phase/shared GPU allocation admission cap reached')
        if counter.get('reference_chat_boundary_attempts_received',0)-self.initial_counter.get('reference_chat_boundary_attempts_received',0)>=self.auth['max_chat_boundaries']:
            raise RuntimeError('Reference provider-boundary attempt cap reached')
        if counter['chat_requests_reserved']-self.initial_counter['chat_requests_reserved']>=self.auth['max_reserved_generation_requests']:
            raise RuntimeError('Reference generation-reservation cap reached')
        if counter.get('reference_embedding_boundary_attempts_received',0)-self.initial_counter.get('reference_embedding_boundary_attempts_received',0)>=self.auth['max_embedding_boundaries']:
            raise RuntimeError('Reference embedding-boundary cap reached')
        return remaining,health

    def perform(self,allocation_id,operation,*,chat=False):
        remaining,health=self.budget();before=health['counters']
        event_offset=len(rows(self.state/'requests.jsonl'))
        maximum=3 if chat else 0
        lifetime=min(remaining,self.auth['max_native_timeout_seconds'])
        opening_io=atomic(self.state/'ACTIVE_ALLOCATION.json',{'allocation_id':allocation_id,
            'phase':self.auth['provider_phase'],'chat_request_baseline':before['chat_requests_reserved'],
            'max_chat_requests':maximum,'exclusive_serial_root_owner':True,
            'opened_at_utc':utc(),'expires_at_epoch':time.time()+lifetime,
            'aggregate_allowance_id':self.auth['aggregate_allowance_id']})
        started=time.perf_counter();value=None;error=None
        try:value=operation(lifetime)
        except Exception as exception:error=repr(exception)
        finally:
            closing_io=atomic(self.state/'ACTIVE_ALLOCATION.json',{'allocation_id':'CLOSED','phase':self.auth['provider_phase'],
                'chat_request_baseline':before['chat_requests_reserved'],'max_chat_requests':0,'expires_at_epoch':time.time()})
        native_wall=time.perf_counter()-started
        deadline=time.monotonic()+2.;joined=None;related=[];after=before;join_error=None
        while True:
            try:
                new=rows(self.state/'requests.jsonl')[event_offset:]
                related=new # Preserve foreign/unbound attempts as incidents too.
                if any(x.get('allocation_id')!=allocation_id for x in new):raise RuntimeError('Concurrent provider activity violated exclusive reference dispatch')
                after=self.health()['counters'];joined=provider_join(before,after,related,allow_chat=chat,
                    expected_backend_receipt=self.auth['backend_receipt_sha256'],require_boundary_counters=True)
                if joined['joined']:break
            except (OSError,ValueError) as exception:joined=None;join_error=repr(exception)
            except RuntimeError as exception:joined=None;join_error=repr(exception);break
            if time.monotonic()>=deadline:break
            time.sleep(.05)
        receipt={'allocation_id':allocation_id,'started_counter':before,'finished_counter':after,
                 'native_wall_seconds':native_wall,'adapter_exception':error,'join_error':join_error,'native_result':value,
                 'allocation_open_file_io':opening_io,'allocation_close_file_io':closing_io,
                 'provider_join':joined,'provider_receipts':related,'finished_at_utc':utc()}
        receipt['study_incidents']=study_incidents(value,related)
        if joined is None or not joined['joined'] or joined['attempt_cap_exceeded']:
            receipt['study_incidents'].append('study_provider_receipt_binding_metering_or_cap_unresolved')
        append(self.run/'sealed/provider_joins.jsonl',receipt)
        if joined is None or not joined['joined'] or joined['attempt_cap_exceeded'] or receipt['study_incidents']:
            write_new(self.run/'ACCOUNTING_BLOCK.json',receipt)
        receipt['dispatch_safe_to_continue']=joined is not None and joined['joined'] and not joined['attempt_cap_exceeded'] and not receipt['study_incidents']
        return value,receipt

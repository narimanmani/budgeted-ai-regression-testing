"""Controlled native pilot provider phase, preserving actual upstream generation and CPU embeddings.

Transport, durable counters, allocation guards and pending-work handling are reused
from the completed native reference implementation. Counter-key prefixes are legacy
transport names; scientific role/trajectory is assigned by the v6 controller.
Original source and prior state directories are never modified.
"""
from datetime import datetime, timezone
import argparse
from copy import deepcopy
import hashlib
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.request import ProxyHandler, build_opener

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiment'))
from native_v3.provider import server as original
from native_v3.provider_llamacpp import bridge

PHASE='EXTERNAL_V8'
ProviderError=original.ProviderError


class Runtime(original.Runtime):
    def __init__(self,args,*,opener=None):
        if type(args.generation_cap) is not int or args.generation_cap <= 0:
            raise ValueError('Reference generation cap must be explicitly priced and positive')
        bridge._finite(args.gpu_cap_seconds,'Reference GPU allocation cap',positive=True)
        self.startup_gpu_seconds=bridge._finite(args.startup_gpu_seconds,'Actual incremental startup allocation')
        self.prior_shared_gpu_seconds=bridge._finite(args.prior_shared_gpu_seconds,'Prior shared actual allocation')
        self.shared_gpu_cap_seconds=bridge._finite(args.shared_gpu_cap_seconds,'Shared allocation cap',positive=True)
        if self.shared_gpu_cap_seconds > 43200:raise ValueError('Do not increase the shared12-hour cap')
        if type(args.max_chat_requests_per_native) is not int or args.max_chat_requests_per_native <= 0:
            raise ValueError('Per-native provider limit must be explicitly frozen')
        for name in ('max_input_tokens','max_new_tokens'):
            if type(getattr(args,name)) is not int or getattr(args,name) <= 0:raise ValueError('Invalid '+name)
        bridge._finite(args.upstream_timeout_seconds,'Upstream timeout',positive=True)
        if args.upstream.rstrip('/') != 'http://127.0.0.1:33002':
            raise ValueError('Reference bridge uses only the root-pinned loopback backend33002')
        self.upstream=args.upstream.rstrip('/');self.opener=opener or build_opener(ProxyHandler({}))
        receipt=args.backend_receipt.read_bytes();self.backend_receipt=json.loads(receipt)
        if not isinstance(self.backend_receipt,dict):raise ValueError('Backend provenance must be a JSON object')
        self.backend_receipt_sha256=hashlib.sha256(receipt).hexdigest()
        directory=args.state_dir.resolve();directory.mkdir(parents=True,exist_ok=True)
        identity={'phase':PHASE,'model':bridge.CHAT_MODEL,'upstream':self.upstream,
                  'backend_receipt_sha256':self.backend_receipt_sha256,'generation_cap':args.generation_cap,
                  'gpu_cap_seconds':args.gpu_cap_seconds,'startup_gpu_seconds':self.startup_gpu_seconds,
                  'prior_shared_gpu_seconds':self.prior_shared_gpu_seconds,'shared_gpu_cap_seconds':self.shared_gpu_cap_seconds,
                  'max_chat_requests_per_native':args.max_chat_requests_per_native,
                  'max_input_tokens':args.max_input_tokens,'max_new_tokens':args.max_new_tokens,
                  'cache_policy':bridge.CACHE_POLICY}
        lock=directory/'EXTERNAL_V8_PHASE_LOCK.json'
        if lock.exists():
            if json.loads(lock.read_text(encoding='utf-8-sig')) != identity:
                raise RuntimeError('Reference phase is already locked to different caps/provenance')
        else:
            if (directory/'COUNTER.json').exists() or (directory/'requests.jsonl').exists():
                raise RuntimeError('Use a separate reference state directory; never reuse S0/Q1 counters')
            bridge._atomic(lock,identity)
        super().__init__(args)
        self.pending_path=directory/'UPSTREAM_PENDING.json';self.upstream_pending_memory=False
        if not self.counter.snapshot().get('reference_backend_startup_debited'):
            self.counter.add(reference_backend_startup_debited=1,gpu_allocation_seconds_accounted=self.startup_gpu_seconds)
        startup=directory/'BACKEND_STARTUP_DEBIT.json'
        if not startup.exists():
            event={'request_id':PHASE+'-BACKEND-STARTUP','path':'/__backend_startup__','allocation_id':PHASE+'_STARTUP',
                   'phase':PHASE,'model_setup_gpu_allocation_seconds':self.startup_gpu_seconds,
                   'model_setup_succeeded':True,'hf_generate_started':False,
                   'backend_receipt_sha256':self.backend_receipt_sha256,'gpu_cost_accounted_in_persisted_counter':True,
                   'gpu_cost_kind':'Declared measured incremental startup allocation;0 only when no reload actually occurred and prior phase paid it'}
            self.record(event);bridge._atomic(startup,event)

    def validate_allocation(self,allocation):
        if self.pending_path.exists() or self.upstream_pending_memory:
            raise ProviderError(503,'Unresolved upstream work blocks new CPU and GPU reference work','upstream_pending')
        if not isinstance(allocation,dict) or allocation.get('phase') != PHASE:
            raise ProviderError(503,'EXTERNAL_V8 allocation is required; S0/Q1 are not accepted','wrong_reference_phase')
        ident=allocation.get('allocation_id')
        if not isinstance(ident,str) or not ident or ident.upper() in ('CLOSED','NONE'):
            raise ProviderError(503,'Explicit live reference allocation identity required','missing_allocation_identity')
        expiry=allocation.get('expires_at_epoch')
        if isinstance(expiry,bool) or not isinstance(expiry,(int,float)) or not math.isfinite(expiry):
            raise ProviderError(503,'Reference allocation needs a finite expiry','invalid_allocation_expiry')
        if time.time() >= expiry:
            raise ProviderError(429,'Reference allocation expired; no new CPU/GPU work admitted','allocation_expired')
        if self.counter.snapshot().get('counter_persistence_failed'):
            raise ProviderError(503,'Counter persistence unresolved; no new reference work','counter_persistence_pending')
        return allocation

    def receive_boundary(self,path):
        """Persist receipt before parsing/admission/work, including rejects.

        The three monotone counters let collectors distinguish zero requests
        from a request whose final event has not yet been appended. They are
        not actual CPU/model invocation counts or successful responses.
        """
        field={'/v1/chat/completions':'reference_chat_boundary_attempts_received',
               '/v1/embeddings':'reference_embedding_boundary_attempts_received'}[path]
        with self.counter.lock:
            if self.counter.persistence_failed:
                raise ProviderError(503,'Unresolved counter persistence; boundary rejected before provider work','counter_persistence_pending')
            for name in ('reference_boundary_attempts_received',field):
                self.counter.data[name]=self.counter.data.get(name,0)+1
            self.counter.save()
            return {'reference_boundary_attempt_number':self.counter.data['reference_boundary_attempts_received'],
                    'reference_route_boundary_attempt_number':self.counter.data[field],
                    'reference_boundary_counter_field':field,
                    'reference_boundary_durably_received_before_provider_work':True}

    def active_allocation(self):
        # Original Handler calls this before parsing/queueing BOTH endpoint
        # types, so CPU indexing/query embeddings cannot bypass allocation.
        return self.validate_allocation(super().active_allocation())

    def guard_chat_admission(self,allocation,event):
        try:
            self.validate_allocation(allocation)
            maximum=allocation.get('max_chat_requests')
            if type(maximum) is not int or not 0 <= maximum <= self.args.max_chat_requests_per_native:
                raise ProviderError(503,'Per-native reference provider limit exceeded/invalid','invalid_allocation')
            if self.pending_path.exists() or self.upstream_pending_memory:
                raise ProviderError(503,'Actual upstream work remains unresolved','upstream_pending')
            super().guard_chat_admission(allocation,event)
            if self.prior_shared_gpu_seconds+self.gpu_cost_so_far() >= self.shared_gpu_cap_seconds:
                raise ProviderError(429,'Shared12-hour budget exhausted','shared_gpu_cap_reached')
        except ProviderError:
            self.counter.add(reference_admission_rejections=1);raise

    def chat(self,body,event):
        try:
            if body.get('model') != bridge.CHAT_MODEL:
                raise ProviderError(400,'Unknown EXTERNAL_V8 model; use '+bridge.CHAT_MODEL,'wrong_model')
            return bridge.Runtime.chat(self,body,event)
        finally:
            # The imported implementation uses a Q1 module constant internally;
            # every committed reference event is explicitly this new phase.
            event['phase']=PHASE;event['reference_collection']=True
            event['implementation_reuse']='patched bridge.Runtime.chat; actual upstream output unchanged'

    def embeddings(self,body,event):
        # Invoked after original Handler acquires runtime_lock. Revalidate both
        # expiry and identity here, not only at request arrival before queueing.
        current=self.active_allocation()
        if current != event.get('allocation'):
            raise ProviderError(429,'Reference allocation changed while CPU request queued','allocation_changed_after_queue')
        event.update(phase=PHASE,embedding_allocation_id=current['allocation_id'],
                     embedding_allocation_valid_at_cpu_start=True,
                     embedding_nonpreemptible_after_admission=True)
        started=time.perf_counter()
        try:
            return original.Runtime.embeddings(self,body,event)
        finally:
            event['reference_cpu_embedding_work_wall_seconds']=time.perf_counter()-started
            event['embedding_finished_after_allocation_expiry']=time.time() >= current['expires_at_epoch']
            event['embedding_late_semantics']='Admitted running CPU call may finish late; no hard cancellation or timely credit claimed; next request is revalidated.'

    def record(self,row):
        value=deepcopy(row);value['phase']=PHASE
        value['provider_wrapper']='reference_bridge.py; separate phase/state from S0 and Q1'
        super().record(value)

    def get_generator(self):
        raise ProviderError(503,'HF generation is disabled for EXTERNAL_V8','wrong_generation_backend')

    def get_tokenizer(self):
        raise ProviderError(503,'EXTERNAL_V8 uses its pinned native backend tokenizer','wrong_generation_backend')

    backend_health=bridge.Runtime.backend_health


class Handler(original.Handler):
    emit_stream=bridge.Handler.emit_stream

    def do_GET(self):
        if self.path in ('/health','/v1/health'):
            backend=self.runtime.backend_health()
            self.json_response(200,{'status':'ok' if backend['ready'] else 'upstream_not_ready','phase':PHASE,
                'generation_loaded':backend['ready'],'upstream_backend':backend,'model_loaded_by_bridge':False,
                'public_model':bridge.CHAT_MODEL,'embedding_device':'cpu','embedding_loaded':self.runtime.embedder is not None,
                'generation_cap':self.runtime.args.generation_cap,'gpu_cap_seconds':self.runtime.args.gpu_cap_seconds,
                'max_input_tokens':self.runtime.args.max_input_tokens,'max_new_tokens':self.runtime.args.max_new_tokens,
                'backend_receipt_sha256':self.runtime.backend_receipt_sha256,'cache_policy':bridge.CACHE_POLICY,
                'counters':self.runtime.counter.snapshot(),'prior_shared_gpu_seconds':self.runtime.prior_shared_gpu_seconds,
                'shared_gpu_allocation_seconds':self.runtime.prior_shared_gpu_seconds+self.runtime.gpu_cost_so_far(),
                'embedding_allocation_required':True,'embedding_rechecked_after_queue':True,
                'boundary_attempt_counters_supported':True,
                'upstream_pending':self.runtime.pending_path.exists() or self.runtime.upstream_pending_memory,
                'running_calls_nonpreemptible':True,'gpu_cap_is_admission_only':True})
        elif self.path == '/v1/models':
            self.json_response(200,{'object':'list','data':[{'id':name,'object':'model','owned_by':'local-pinned'}
                                                         for name in (bridge.CHAT_MODEL,original.EMBED_MODEL)]})
        else:self.json_response(404,{'error':{'message':'Unknown route','type':'invalid_request_error'}})

    def do_POST(self):
        # Separate reference-only copy of the original transport protocol.
        # The sole protocol addition is durable supported-route entry counts.
        event={'request_id':uuid.uuid4().hex,'path':self.path,
               'started_at_utc':datetime.now(timezone.utc).isoformat(),
               'client_address':self.client_address[0],'hf_generate_started':False,
               'correlation_headers':{key:value for key,value in self.headers.items() if key.lower().startswith('x-tosem-')},
               'authorization_logged':False}
        started=time.perf_counter();status=500
        try:
            if self.path not in ('/v1/chat/completions','/v1/embeddings'):
                raise ProviderError(404,'Unknown route')
            event.update(self.runtime.receive_boundary(self.path))
            allocation=self.runtime.active_allocation()
            event['allocation']=allocation;event['allocation_id']=allocation['allocation_id']
            if self.path=='/v1/chat/completions':
                self.runtime.guard_chat_admission(allocation,event)
                event['generation_request_number']=self.runtime.counter.reserve_chat(allocation)
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 4*1024*1024:raise ProviderError(400,'Body length missing or exceeds4MiB')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ProviderError(400,'JSON object required')
            event['request']=body;wait=time.perf_counter()
            with self.runtime.runtime_lock:
                event['serialization_wait_seconds']=time.perf_counter()-wait
                try:
                    if self.path=='/v1/chat/completions':
                        current=self.runtime.active_allocation()
                        if current != allocation:raise ProviderError(429,'Allocation changed while queued','allocation_changed')
                        self.runtime.guard_chat_admission(current,event)
                    response=self.runtime.chat(body,event) if self.path=='/v1/chat/completions' else self.runtime.embeddings(body,event)
                finally:self.runtime.account_gpu_event(event)
            status=200
            event['response']=response if self.path=='/v1/chat/completions' else {'model':response['model'],'usage':response['usage'],'embedding_count':len(response['data'])}
            if body.get('stream') and self.path=='/v1/chat/completions':self.emit_stream(response,body)
            else:self.json_response(status,response)
        except ProviderError as error:
            status=error.status;event['error']={'message':error.message,'type':error.code}
            self.json_response(status,{'error':event['error']})
        except (ValueError,json.JSONDecodeError) as error:
            status=400;event['error']={'message':str(error),'type':'invalid_request_error'}
            self.json_response(status,{'error':event['error']})
        except (BrokenPipeError,ConnectionResetError) as error:event['client_disconnected']=str(error)
        except Exception as error:
            status=500;event['error']={'message':str(error),'type':type(error).__name__}
            try:self.json_response(status,{'error':event['error']})
            except (BrokenPipeError,ConnectionResetError):event['client_disconnected']=True
        finally:
            cost=self.runtime.gpu_cost_so_far()
            event.update(http_status=status,finished_at_utc=datetime.now(timezone.utc).isoformat(),
                         handler_seconds=time.perf_counter()-started,counters=self.runtime.counter.snapshot(),
                         gpu_allocation_total_after_request=cost,
                         gpu_cap_overshoot_seconds=max(cost-self.runtime.args.gpu_cap_seconds,0),
                         gpu_cap_is_admission_only=True)
            self.runtime.record(event)


def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=33001)
    parser.add_argument('--state-dir',type=Path,required=True);parser.add_argument('--backend-receipt',type=Path,required=True)
    parser.add_argument('--generation-cap',type=int,required=True);parser.add_argument('--gpu-cap-seconds',type=float,required=True)
    parser.add_argument('--max-chat-requests-per-native',type=int,required=True)
    parser.add_argument('--startup-gpu-seconds',type=float,required=True);parser.add_argument('--prior-shared-gpu-seconds',type=float,required=True)
    parser.add_argument('--shared-gpu-cap-seconds',type=float,default=43200)
    parser.add_argument('--upstream',default='http://127.0.0.1:33002');parser.add_argument('--upstream-timeout-seconds',type=float,default=180)
    parser.add_argument('--max-input-tokens',type=int,default=8192);parser.add_argument('--max-new-tokens',type=int,default=512)
    parser.add_argument('--embedding-dir',type=Path,default=ROOT/'experiment/models/all_minilm_l6_v2')
    return parser.parse_args()


def main():
    args=arguments()
    if args.host not in ('127.0.0.1','localhost','::1'):raise ValueError('Reference provider must remain loopback only')
    args.state_dir.mkdir(parents=True,exist_ok=True);owner=args.state_dir/'REFERENCE_BRIDGE_OWNER.json'
    with owner.open('x',encoding='utf-8') as stream:json.dump({'pid':os.getpid(),'phase':PHASE},stream)
    try:
        runtime=Runtime(args);Handler.runtime=runtime
        print(json.dumps({'listening':f'http://{args.host}:{args.port}','phase':PHASE,'state_dir':str(runtime.directory),
                          'model_loaded_by_wrapper':False,'generation_cap':args.generation_cap}),flush=True)
        ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
    finally:owner.unlink(missing_ok=True)


if __name__=='__main__':main()

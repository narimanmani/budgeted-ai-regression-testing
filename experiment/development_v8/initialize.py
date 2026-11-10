"""Start a separate bounded v8 segment, retaining every preceding physical cost."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import build_opener, ProxyHandler
import hashlib
import json
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'experiment/runs/development_v8_20261101'
PRIOR=ROOT/'experiment/runs/validation_v7_20261101'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    digest=hashlib.sha256()
    with Path(p).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):digest.update(block)
    return digest.hexdigest()
def save(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2);stream.write('\n')
def utc():return datetime.now(timezone.utc).isoformat()

def main():
    prior_path=PRIOR/'FINAL_ACCOUNTING_AND_CLEANUP.json';prior=read(prior_path)
    assert prior['native_units_cumulative']==2071 and prior['all_owned_helpers_closed'] is True
    assert prior['cumulative_generation_allocation_seconds']==9316.086159400991
    closed=read(PRIOR/'OWNED_HELPERS_CLEANUP.json')
    assert sha(PRIOR/'provider_compact/COUNTER.json')==closed['counter_sha256_before_and_after']
    assert read(PRIOR/'provider_compact/ACTIVE_ALLOCATION.json')['allocation_id']=='CLOSED'
    guide=ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'
    for relative,expected in read(guide)['frozen_files_sha256'].items():
        if sha(ROOT/relative)!=expected:raise RuntimeError('Frozen guidance/design changed')
    memory=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',
        'Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress'],text=True))
    if memory['FreePhysicalMemory']/1024**2<3.0:raise RuntimeError('Insufficient measured host memory for compact model startup')
    RUN.mkdir(exist_ok=False);backend=RUN/'backend';backend.mkdir()
    assets=read(ROOT/'experiment/runs/validation_v7_20261101/backend/ASSET_RECHECK.json')
    for row in assets['files_verified']:
        path=Path(row['path'])
        if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:
            raise RuntimeError('Pinned backend/model asset changed: '+str(path))
    save(backend/'ASSET_RECHECK.json',{'verified_at_utc':utc(),'files_verified':assets['files_verified'],
        'template_sha256':sha(ROOT/'experiment/native_v3/provider_llamacpp/qwen2_5_7b_official.jinja')})
    old=read(PRIOR/'backend_compact/BACKEND_PROVENANCE_COMPACT.json')
    command=read(PRIOR/'backend_compact/START_RECEIPT.json')['command'][:]
    command[command.index('--log-file')+1]=str(backend/'backend.log')
    provenance={**old,'origin_backend_provenance_sha256':sha(PRIOR/'backend_compact/BACKEND_PROVENANCE_COMPACT.json'),
        'launch_command':command,'scope':'V8 development and fresh held-out workloads; same physically rechecked model, binary, template and compact4096/26GPU/F16KV configuration',
        'generation_calls':0,'gpu_model_loaded':False,'later_measurements':[]}
    source_receipt=backend/'BACKEND_PROVENANCE.json';save(source_receipt,provenance)
    out=(backend/'stdout.log').open('xb');err=(backend/'stderr.log').open('xb')
    started=time.perf_counter();process=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    launch={'pid':process.pid,'command':command,'started_at_utc':utc(),'warmup_disabled':True,
        'generation_requests_dispatched':0,'backend_provenance_sha256':sha(source_receipt)}
    save(backend/'START_RECEIPT.json',launch)
    opener=build_opener(ProxyHandler({}))
    while time.perf_counter()-started<90:
        if process.poll() is not None:raise RuntimeError('Pinned compact model backend failed startup; preserve its receipts')
        try:
            with opener.open('http://127.0.0.1:33002/health',timeout=2) as response:health=json.load(response)
            if health.get('status')=='ok':break
        except Exception:time.sleep(.25)
    else:raise RuntimeError('Compact model startup lifetime exhausted')
    startup=time.perf_counter()-started
    save(backend/'LOAD_RECEIPT.json',{**launch,'ready_at_utc':utc(),'startup_gpu_allocation_seconds':startup,'health':health})
    expiry=time.time()+16*3600
    auth={'provider_phase':'EXTERNAL_V8','campaign_run_dir':str(RUN),'provider_state_dir':str(RUN/'provider'),
        'control_source_sha256':sha(HERE/'control.py'),
        'provider_meter_source_sha256':sha(ROOT/'experiment/native_v3/librechat/history/reference/provider_meter.py'),
        'expires_at_epoch':expiry,'model_id':'tosem-qwen2.5-7b-q4','backend_receipt_sha256':sha(source_receipt),
        'wall_seconds_cap':43200,'phase_gpu_cap_seconds':30000,
        'prior_shared_gpu_seconds':prior['cumulative_generation_allocation_seconds'],'shared_gpu_cap_seconds':43200,
        'max_chat_boundaries':8787,'max_reserved_generation_requests':8787,'max_embedding_boundaries':40000,
        'max_native_timeout_seconds':600,'aggregate_allowance_id':'EXTERNAL_V8_20261101',
        'native_query_cap':2929,'prior_native_query_units':2071,'shared_native_query_cap':5000,
        'guidance_freeze_sha256':sha(guide),'prior_cost_record_sha256':sha(prior_path)}
    save(RUN/'CAMPAIGN_AUTH.json',auth)
    save(RUN/'INFRASTRUCTURE_AUTH.json',{'phase':'EXTERNAL_V8','stage_id':'infrastructure_probes',
        'campaign_auth_sha256':sha(RUN/'CAMPAIGN_AUTH.json'),'authorized':True,'expires_at_epoch':expiry,
        'allowed_states':['INFRA'],'allowed_tasks':['PROVIDER_VALIDATE'],
        'allowed_metadata_phases':['setup_probe'],'native_query_cap':305})
    save(RUN/'RUNTIME_AUTH.json',{'provider_phase':'EXTERNAL_V8','allow_native_openwebui':True,'allow_native_dify':True,
        'allowed_base_urls':[f'http://127.0.0.1:{port}' for port in (33511,33512,33513,33381,33382,33383)],
        'provider_state_dir':str(RUN/'provider'),'provider_endpoint':'http://host.docker.internal:33001/v1',
        'run_root':str(RUN),'expires_at_epoch':expiry,'guidance_freeze_sha256':sha(guide),'model_context_tokens':4096,
        'maximum_resident_native_API_states':2})
    interpreter=ROOT.parent/'AST - from ICST 2026/experiment/.venv/Scripts/python.exe'
    command=[str(interpreter),str(HERE/'provider_bridge.py'),'--state-dir',str(RUN/'provider'),
        '--backend-receipt',str(source_receipt),'--generation-cap','8787','--gpu-cap-seconds','30000',
        '--max-chat-requests-per-native','3','--startup-gpu-seconds',str(startup),
        '--prior-shared-gpu-seconds',str(prior['cumulative_generation_allocation_seconds']),
        '--shared-gpu-cap-seconds','43200','--max-input-tokens','4096']
    out=(RUN/'provider_stdout.log').open('xb');err=(RUN/'provider_stderr.log').open('xb')
    process=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    save(RUN/'PROVIDER_START.json',{'pid':process.pid,'command':command,'started_at_utc':utc()})
    save(RUN/'SEGMENT_DECLARATION.json',{'at_utc':utc(),'phase':'EXTERNAL_V8',
        'prior_receipt_path':str(prior_path),'prior_receipt_sha256':sha(prior_path),
        'prior_native_units':2071,'prior_generation_allocation_seconds':prior['cumulative_generation_allocation_seconds'],
        'incremental_startup_generation_allocation_seconds':startup,
        'new_scientific_questions_dispatched':0,'host_memory_before':memory,
        'model_or_template_or_guidance_bytes_changed':False,'new_provider_source_sha256':sha(HERE/'provider_bridge.py'),
        'native_state_execution_scope':'At most two API states resident; serial ingestion and metered state preparation before timed comparisons',
        'old_campaigns_sources_or_counters_modified':False})
    print(json.dumps({'run_root':str(RUN),'backend_pid':launch['pid'],'provider_wrapper_pid':process.pid,
        'startup_generation_allocation_seconds':startup,'native_scientific_queries':0}),flush=True)

if __name__=='__main__':main()

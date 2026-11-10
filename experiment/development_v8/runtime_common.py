"""Shared native authorization and public cohort identity; no dispatch here."""
from pathlib import Path
import hashlib
import json
import re
import time

ROOT=Path(__file__).resolve().parents[2]

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def text_sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()

def initialize(runtime,config):
    required=('cohort_dir','cohort_id','prompt_id','prompt_text','input_freeze_file','input_freeze_sha256','receipt_scope')
    if any(not isinstance(config.get(key),str) or not config[key] for key in required):
        raise ValueError('Explicit cohort, generic prompt, frozen-input receipt and receipt namespace required')
    if not re.fullmatch('[0-9a-f]{64}',config['input_freeze_sha256']):raise ValueError('Frozen-input SHA256 required')
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',config['receipt_scope']):raise ValueError('Safe unique receipt namespace required')
    runtime.cohort=Path(config['cohort_dir']).resolve()
    if not runtime.cohort.is_relative_to(ROOT):raise ValueError('Cohort outside this research workspace')
    runtime.cohort_id=config['cohort_id'];runtime.prompt_id=config['prompt_id'];runtime.prompt_text=config['prompt_text']
    runtime.input_freeze=Path(config['input_freeze_file']).resolve();runtime.input_freeze_sha=config['input_freeze_sha256']
    runtime.receipt_scope=config['receipt_scope']
    runtime.scope_id=config.get('scope_id',runtime.cohort_id+'-'+runtime.prompt_id)
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',runtime.scope_id):raise ValueError('Safe native dataset scope required')

def identity(runtime):
    return {'cohort_id':runtime.cohort_id,'cohort':runtime.cohort_id,'prompt_candidate_id':runtime.prompt_id,
        'prompt_id':runtime.prompt_id,'prompt_text_sha256':text_sha(runtime.prompt_text),
        'prompt_sha256':text_sha(runtime.prompt_text),'input_freeze_sha256':runtime.input_freeze_sha,
        'scope_id':runtime.scope_id}

def authorize(runtime,auth_path,application):
    auth=read(auth_path)
    if (runtime.config.get('allow_native') is not True or auth.get('allow_native_'+application) is not True
        or auth.get('provider_phase')!='EXTERNAL_V8' or time.time()>=auth['expires_at_epoch']
        or not runtime.run.is_relative_to(Path(auth['run_root']).resolve())):
        raise RuntimeError('No current v8 native allowance for this exact run')
    if sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json')!=auth['guidance_freeze_sha256']:
        raise RuntimeError('Original CG1 guidance freeze changed')
    if sha(runtime.input_freeze)!=runtime.input_freeze_sha:raise RuntimeError('Frozen input receipt changed')
    freeze=read(runtime.input_freeze);mapping=freeze.get('files_sha256')
    if (not isinstance(mapping,dict) or not mapping or freeze.get('prompt_id')!=runtime.prompt_id
        or freeze.get('prompt_text_sha256',freeze.get('prompt_sha256'))!=text_sha(runtime.prompt_text)
        or freeze.get('cohort_id',freeze.get('cohort'))!=runtime.cohort_id):
        raise RuntimeError('Frozen cohort/prompt identity differs from native configuration')
    bound=set()
    for recorded,expected in mapping.items():
        path=Path(recorded);path=(path if path.is_absolute() else ROOT/path).resolve()
        if not path.is_relative_to(ROOT) or sha(path)!=expected:raise RuntimeError('Frozen input bytes changed: '+str(recorded))
        bound.add(path)
    if not {runtime.cohort/'tasks.json',runtime.cohort/'source_manifest.json'}<=bound:
        raise RuntimeError('Actual native task/source catalogs are not frozen')
    active=read(Path(auth['provider_state_dir'])/'ACTIVE_ALLOCATION.json')
    if (not runtime.allocation_id or active.get('allocation_id')!=runtime.allocation_id
        or active.get('phase')!='EXTERNAL_V8' or time.time()>=active['expires_at_epoch']):
        raise RuntimeError('No matching live root allocation')
    runtime._remaining();return auth

def tasks(runtime):
    values=read(runtime.cohort/'tasks.json')['tasks']
    if len(values)!=8 or len({row['id'] for row in values})!=8:raise RuntimeError('Exactly eight distinct public tasks required')
    return {row['id']:row for row in values}

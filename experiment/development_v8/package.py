"""Public v8 evidence packaging and manifest-only saved-output reanalysis.

No command starts applications, providers, models, containers or network calls.
Original receipt bytes and historical absolute paths are preserved. The read
resolver never consults their original locations, even if those locations exist.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import fnmatch
import importlib.util
import importlib
import contextlib
import types
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = 'ARTIFACT_MANIFEST.json'
GUIDE = 'ARTIFACT_README.md'
SCHEMA = 8
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
PUBLIC_SUFFIXES = {'.py','.json','.jsonl','.md','.txt','.csv','.log','.yaml','.yml',
                   '.toml','.patch','.diff','.mbox','.jinja','.jinja2','.sh','.ps1','.example','.html'}
NOTICE_NAMES={'license','notice','copying'}
UPSTREAM_NOTICE_SOURCES={'openwebui':'SOURCE_MANIFEST.json','dify':'SOURCE_CASE_MANIFEST.json'}
PRIVATE_PARTS = {'private','.git','.ssh','__pycache__','.pytest_cache','node_modules',
                 '.venv','venv','site-packages','downloads','bin','.uv_cache','component_deps'}
SECRET_NAMES = {'.env','apikeys','apikeys.json','credentials','credentials.json','secrets.json'}
FORBIDDEN_SUFFIXES = {'.db','.db3','.sqlite','.sqlite3','.pem','.key','.p12','.pfx',
                      '.gguf','.safetensors','.bin','.dll','.exe','.zip','.difypkg',
                      '.png','.jpg','.jpeg','.svg','.mp3','.mp4','.pdf','.pyc'}
SECRET_PATTERNS = (
 ('overleaf_token',re.compile(rb'olp_[A-Za-z0-9]{20,}')),
 ('openai_token',re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{20,}')),
 ('github_token',re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})')),
 ('aws_access_key',re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}')),
 ('private_key',re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
 ('credential_url',re.compile(rb'https?://[^\s/:@]+:[^\s/@]+@')),
 ('authorization_value',re.compile(rb'(?i)authorization\s*[:=]\s*["\x27]?(?:bearer|basic)\s+[A-Za-z0-9_+/=.-]{12,}')),
)
SECRET_KEYS = {'apikey','apikeys','apisecret','authorization','password','passwd',
 'secret','token','accesstoken','refreshtoken','cookie','setcookie','clientsecret',
 'credential','credentials','apptoken','datasettoken'}
PLACEHOLDERS = {'[REDACTED]','local-study-no-paid-key',
 'User explicitly requested freezing conditional guidance and validating independent applications',
 'Root explicitly selected unchanged common v3 checker semantics before main freeze or outputs'}
REPORT='experiment/RESULTS_DEVELOPMENT_V8.md'
PRIOR_RECEIPT='experiment/runs/validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json'
SUPPORT_FILES=(REPORT,PRIOR_RECEIPT,'experiment/validation_v7/GUIDANCE_FREEZE.json',
 'experiment/validation_v7/CASE_SEARCH_FRAME.json','experiment/native_v3/common/__init__.py',
 'experiment/native_v3/common/contracts.py','experiment/native_v3/common/reference.py',
 'experiment/native_v3/librechat/history/reference/provider_meter.py')
EXTERNAL_PLUGIN='experiment/validation_v7/dify/provider_package/openai_api_compatible-0.0.73.difypkg'
POLICY_SHA256='f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989'
GUIDANCE_FREEZE_SHA256='92e6d36aa3dd29d10ad06ca040d138a2ea73504a7aa15e981af474460f4b79d9'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
def sha_bytes(raw):return hashlib.sha256(raw).hexdigest()
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def json_rows(path):return [json.loads(x) for x in Path(path).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def safe_member(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:raise ValueError('Unsafe archive path')
    if PurePosixPath(value).is_absolute() or any(x in {'','.','..'} for x in value.split('/')):raise ValueError('Unsafe archive path')
    return value
def linked(path):return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())

def exclusion(path):
    value=path.as_posix().casefold();parts={p.casefold() for p in path.parts};name=path.name.casefold()
    if parts & PRIVATE_PARTS:return 'private/runtime/cache/dependency tree'
    if (name in SECRET_NAMES or name.startswith('.env') or name=='active_allocation.json'):
        return 'authorization/credential configuration'
    if 'handoff' in name:return 'internal coordination handoff'
    if value=='experiment/validation_v7/dify/metadata/openapi_service.json':
        return 'upstream OpenAPI credential examples; URL and hash provenance retained'
    if path.suffix.casefold() in FORBIDDEN_SUFFIXES:return 'database/key/model/executable/image/archive binary'
    if path.suffix.casefold() not in PUBLIC_SUFFIXES and name not in NOTICE_NAMES|{'dockerfile'}:return 'outside public file-type allowlist'
    return None

def secret_issues(raw,suffix):
    issues=[name for name,pattern in SECRET_PATTERNS if pattern.search(raw)]
    if suffix not in {'.json','.jsonl'}:return issues
    try:
        text=raw.decode('utf-8-sig');values=[json.loads(x) for x in text.splitlines() if x.strip()] if suffix=='.jsonl' else [json.loads(text)]
    except (ValueError,UnicodeError):return issues+['invalid_public_json']
    def walk(value):
        if isinstance(value,dict):
            for key,item in value.items():
                normalized=re.sub('[^a-z0-9]','',key.casefold())
                sensitive=normalized in SECRET_KEYS or normalized.endswith(('apikey','apikeys','apisecret','password','accesstoken','refreshtoken','clientsecret'))
                if sensitive and item not in (None,False,''):
                    if isinstance(item,str) and item not in PLACEHOLDERS:issues.append('nonempty_credential_field:'+key)
                    elif isinstance(item,(dict,list)) and item:issues.append('nonempty_credential_field:'+key)
                walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    for value in values:walk(value)
    return sorted(set(issues))


# V8-specific inventory and saved-data analysis follow below.

def _manifest_entries(manifest):
    if manifest.get('schema_version')!=SCHEMA:raise ValueError('Unsupported artifact manifest')
    entries=manifest.get('files')
    if not isinstance(entries,list) or manifest.get('files_sha256')!=sha_bytes(canonical(entries)):raise ValueError('Manifest file-list digest mismatch')
    names=[safe_member(x['path']) for x in entries]
    if len({x.casefold() for x in names})!=len(names):raise ValueError('Duplicate/case-colliding manifest member')
    if any(exclusion(Path(name)) for name in names):raise ValueError('Forbidden manifest member')
    if any(type(x.get('bytes')) is not int or not 0<=x['bytes']<=MAX_FILE_BYTES for x in entries):raise ValueError('Invalid manifest size')
    if sum(x['bytes'] for x in entries)>MAX_TOTAL_BYTES:raise ValueError('Artifact total too large')
    return {x['path']:x for x in entries}

class Resolver:
    def __init__(self,root,manifest):
        self.root=Path(root).resolve();self.manifest=manifest;self.entries=_manifest_entries(manifest)
        self.names={name.casefold():name for name in self.entries};self.aliases=manifest.get('historical_source_aliases',[])
        self._verified={}
        for row in self.aliases:
            target=safe_member(row['target']);provenance=safe_member(row['provenance'])
            if target not in self.entries or provenance not in self.entries or self.entries[target]['sha256']!=row['sha256']:raise ValueError('Unbound historical alias')
            record=read_json(self.root/provenance)
            if any(record.get(k)!=row[v] for k,v in [('source_path','recorded_path'),('source_sha256','sha256'),('snapshot_sha256','sha256')]):raise ValueError('Historical alias provenance differs')
            if self.relative(record['snapshot_path'])!=target:raise ValueError('Historical alias points to another snapshot')
        self.external=manifest.get('external_dependency_bindings',[])
        for row in self.external:
            if self.relative(row['recorded_path'])!=EXTERNAL_PLUGIN or not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ValueError('Unregistered external dependency exception')
            provenance=safe_member(row['freeze_document'])
            if provenance not in self.entries or read_json(self.root/provenance).get('files_sha256',{}).get(row.get('recorded_key',row['recorded_path']))!=row['sha256']:raise ValueError('External dependency declaration differs from original freeze')
    def relative(self,recorded):
        recorded=str(recorded)
        if not recorded:raise ValueError('Missing recorded evidence path')
        value=recorded.replace('\\','/');origin=self.manifest['original_workspace_root'].replace('\\','/').rstrip('/')
        if value.casefold().startswith(origin.casefold()+'/'):value=value[len(origin)+1:]
        elif re.match(r'^(?:[A-Za-z]:|/)',value):raise ValueError('Recorded host path is outside the original workspace')
        return safe_member(value)
    def resolve(self,recorded,*,expected=None,document=None):
        recorded=str(recorded)
        value=self.relative(recorded);exact=self.names.get(value.casefold())
        choices=[exact] if exact else []
        if expected is not None:
            choices=[name for name in choices if self.entries[name]['sha256']==expected]
            choices += [row['target'] for row in self.aliases if row['recorded_path'].replace('\\','/').casefold()==recorded.replace('\\','/').casefold() and row['sha256']==expected]
        if not choices and document and not re.match(r'^(?:[A-Za-z]:|/)',value):
            relative=(PurePosixPath(document).parent/value).as_posix();safe_member(relative)
            name=self.names.get(relative.casefold())
            if name and (expected is None or self.entries[name]['sha256']==expected):choices=[name]
        choices=sorted(set(choices))
        if len(choices)!=1:raise ValueError('Missing/ambiguous manifest-bound evidence: '+recorded)
        path=self.root/safe_member(choices[0])
        if linked(path) or not path.resolve().is_relative_to(self.root):raise ValueError('Extracted path escapes root')
        entry=self.entries[choices[0]];stat=path.stat();stamp=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        if self._verified.get(choices[0])!=stamp:
            raw=path.read_bytes()
            if len(raw)!=entry['bytes'] or sha_bytes(raw)!=entry['sha256']:raise ValueError('Manifest-bound evidence changed: '+choices[0])
            self._verified[choices[0]]=stamp
        return path
    def original(self,relative):
        relative=safe_member(relative)
        origin=self.manifest['original_workspace_root']
        cls=PureWindowsPath if re.match(r'^[A-Za-z]:',origin) else PurePosixPath
        return str(cls(origin).joinpath(*PurePosixPath(relative).parts))
    def external_dependency(self,recorded,expected):
        return any(self.relative(row['recorded_path'])==self.relative(recorded) and row['sha256']==expected for row in self.external)

def frozen_bindings(value,resolver,document):
    """Verify actual freezes and immutable source/native receipt pointers only.

    Historical cost-counter snapshots and unshipped model/image references remain
    provenance, not false promises that mutable current files equal old hashes.
    """
    count=0;name=PurePosixPath(document).name
    if isinstance(value,dict):
        for key,item in value.items():
            if key in {'receipt_path','root_joined_receipt_path','source_verification_path','source_manifest_path',
                       'cohort_source_manifest_path','native_configuration_receipt_path','canonical_source_recheck_receipt'} and isinstance(item,str):
                expected=value.get(key[:-5]+'_sha256') if key.endswith('_path') else value.get('canonical_source_recheck_sha256')
                resolver.resolve(item,expected=expected,document=document);count+=1
            if key in {'capture','captured_path','canonical_file'} and isinstance(item,str) and re.fullmatch('[0-9a-f]{64}',str(value.get('sha256',''))):
                resolver.resolve(item,expected=value['sha256'],document=document);count+=1
            actual_freeze=_is_freeze_document(document)
            if actual_freeze and key in {'files_sha256','frozen_files_sha256','implementation_sha256','preparation_metadata_sha256','sha256'} and isinstance(item,dict):
                for recorded,expected in item.items():
                    if isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected):
                        if not resolver.external_dependency(recorded,expected):resolver.resolve(recorded,expected=expected,document=document)
                        count+=1
            count+=frozen_bindings(item,resolver,document)
    elif isinstance(value,list):count+=sum(frozen_bindings(x,resolver,document) for x in value)
    return count

def verify_tree(root):
    root=Path(root).resolve();manifest=read_json(root/MANIFEST);entries=_manifest_entries(manifest)
    if (root/GUIDE).read_bytes()!=guide(manifest):raise ValueError('Artifact guide changed')
    paths=list(root.rglob('*'))
    if any(linked(path) for path in paths):raise ValueError('Clean extraction cannot contain linked files/directories')
    actual={p.relative_to(root).as_posix() for p in paths if p.is_file()}
    if actual!=set(entries)|{MANIFEST,GUIDE}:raise ValueError('Use a clean extraction; members differ from manifest')
    resolver=Resolver(root,manifest);bindings=0
    verify_source_notices(manifest,lambda name:resolver.resolve(name).read_bytes())
    for name,entry in entries.items():
        path=resolver.resolve(name);raw=path.read_bytes()
        issues=secret_issues(raw,path.suffix.casefold())
        if issues:raise ValueError('Public artifact scan failed '+name+': '+','.join(issues))
        if path.suffix.casefold() in {'.json','.jsonl'}:
            values=json_rows(path) if path.suffix.casefold()=='.jsonl' else [read_json(path)]
            bindings+=sum(frozen_bindings(value,resolver,name) for value in values)
    return manifest,resolver,bindings

def verify_zip(path):
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist();names=[safe_member(m.filename) for m in members]
        if len({n.casefold() for n in names})!=len(names):raise ValueError('Duplicate ZIP member')
        if any(m.is_dir() or stat.S_ISLNK(m.external_attr>>16) or m.file_size>MAX_FILE_BYTES for m in members):raise ValueError('Unsafe ZIP member')
        if sum(m.file_size for m in members)>MAX_TOTAL_BYTES+2*MAX_FILE_BYTES:raise ValueError('ZIP total too large')
        if MANIFEST not in names or GUIDE not in names:raise ValueError('Archive metadata missing')
        manifest=json.loads(archive.read(MANIFEST));entries=_manifest_entries(manifest)
        if set(names)!=set(entries)|{MANIFEST,GUIDE}:raise ValueError('ZIP members differ from manifest')
        if archive.read(GUIDE)!=guide(manifest):raise ValueError('Artifact guide changed')
        verify_source_notices(manifest,archive.read)
        for name,entry in entries.items():
            raw=archive.read(name)
            if len(raw)!=entry['bytes'] or sha_bytes(raw)!=entry['sha256']:raise ValueError('ZIP evidence changed: '+name)
            if secret_issues(raw,Path(name).suffix.casefold()):raise ValueError('ZIP secret scan failed: '+name)
    return manifest


def _is_freeze_document(name):
    path=PurePosixPath(name)
    return ('FREEZE' in path.name or path.parent.name=='input_freezes'
            or path.name in {'MAIN_SOFTWARE_READY.json','PREDEV_OFFLINE_VALIDATION.json',
                             'RUNTIME_OFFLINE_VALIDATION.json','SECONDARY_RETESTALL_REGISTRATION.json'})


def _host_relative(root,recorded):
    """Creation-time host path admission; never treats a container path as host."""
    value=str(recorded).replace('\\','/');origin=str(root).replace('\\','/').rstrip('/')
    if value.casefold().startswith(origin.casefold()+'/'):value=value[len(origin)+1:]
    elif re.match(r'^(?:[A-Za-z]:|/)',value):raise ValueError('Host dependency lies outside the workspace')
    return safe_member(value)


def _dependency_pairs(value,document):
    """Only promised host-file bindings, not every path-like provenance field."""
    pairs=[]
    if isinstance(value,dict):
        if _is_freeze_document(document):
            for key in ('files_sha256','frozen_files_sha256','implementation_sha256','preparation_metadata_sha256','sha256'):
                mapping=value.get(key)
                if isinstance(mapping,dict):
                    pairs.extend((str(path),digest) for path,digest in mapping.items()
                                 if isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest))
        for key in ('receipt_path','root_joined_receipt_path','source_verification_path','source_manifest_path',
                    'cohort_source_manifest_path','native_configuration_receipt_path','canonical_source_recheck_receipt'):
            recorded=value.get(key)
            if isinstance(recorded,str):pairs.append((recorded,value.get(key[:-5]+'_sha256') if key.endswith('_path') else value.get('canonical_source_recheck_sha256')))
        for key in ('capture','captured_path','canonical_file'):
            if isinstance(value.get(key),str) and re.fullmatch('[0-9a-f]{64}',str(value.get('sha256',''))):
                pairs.append((value[key],value['sha256']))
        for item in value.values():pairs.extend(_dependency_pairs(item,document))
    elif isinstance(value,list):
        for item in value:pairs.extend(_dependency_pairs(item,document))
    return pairs


def _git_object_bytes(repository,revision,relative):
    """Creation-time local Git read only; extracted verification needs no Git."""
    result=subprocess.run(['git','-C',str(repository),'show',revision+':'+relative],
        capture_output=True,check=True,timeout=30)
    return result.stdout


def upstream_notice_inventory(root,selected_names,*,git_object_reader=_git_object_bytes):
    """Retain root licenses and notices governing individually selected sources.

    No repository tree is recursively copied. Bytes remain the checkout bytes;
    a Windows checkout's CRLF relation to its pinned Git object is explicit.
    """
    root=Path(root).resolve();records=[]
    for app,metadata_name in UPSTREAM_NOTICE_SOURCES.items():
        base=root/'experiment/validation_v7'/app;repository=base/'source';metadata=base/metadata_name
        source=read_json(metadata);revision=source['fixed_revision']
        if not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('Exact upstream source revision required for notices')
        directories={repository}
        for name in selected_names:
            path=root/safe_member(name)
            if path.is_relative_to(repository):
                current=path.parent
                while current.is_relative_to(repository):
                    directories.add(current)
                    if current==repository:break
                    current=current.parent
        notices=[]
        for directory in sorted(directories):
            if not directory.is_dir():raise ValueError('Selected upstream source directory is missing')
            for path in sorted(directory.iterdir()):
                name=path.name.casefold()
                if name not in NOTICE_NAMES and not (path.stem.casefold() in NOTICE_NAMES and path.suffix.casefold() in {'.txt','.md'}):continue
                if not path.is_file() or linked(path):raise ValueError('Upstream notice must be a regular unlinked file')
                relative=path.relative_to(repository).as_posix();raw=path.read_bytes();pinned=git_object_reader(repository,revision,relative)
                if raw==pinned:relation='byte_identical'
                elif raw.replace(b'\r\n',b'\n')==pinned:relation='CRLF_checkout_matches_LF_pinned_object'
                else:raise ValueError('Upstream notice differs from its pinned source object: '+app+'/'+relative)
                notices.append({'path':path.relative_to(root).as_posix(),'repository_relative_path':relative,
                    'bytes':len(raw),'sha256':sha_bytes(raw),'pinned_object_bytes':len(pinned),
                    'pinned_object_sha256':sha_bytes(pinned),
                    'pinned_git_blob_sha1':hashlib.sha1(b'blob '+str(len(pinned)).encode()+b'\0'+pinned).hexdigest(),
                    'checkout_to_pinned_relation':relation,'notice_bytes_rewritten':False})
        if not any(row['repository_relative_path']=='LICENSE' for row in notices):raise ValueError('Pinned upstream root LICENSE is required: '+app)
        records.append({'application_id':app,'fixed_revision':revision,'source_manifest_path':metadata.relative_to(root).as_posix(),
            'source_manifest_sha256':sha_bytes(metadata.read_bytes()),'notices':notices,
            'scope':'Original upstream terms retained for selected source files; no umbrella relicensing or legal-compliance attestation'})
    return records


def verify_source_notices(manifest,read_bytes):
    records=manifest.get('upstream_source_notices')
    if records is None:return 0  # Minimal synthetic manifests need no upstream source.
    if not isinstance(records,list) or {row.get('application_id') for row in records}!=set(UPSTREAM_NOTICE_SOURCES) or len(records)!=2:
        raise ValueError('Both exact upstream notice provenance records are required')
    entries=_manifest_entries(manifest);count=0
    for record in records:
        metadata_name=safe_member(record['source_manifest_path']);metadata=read_bytes(metadata_name)
        if metadata_name not in entries or sha_bytes(metadata)!=record['source_manifest_sha256'] or json.loads(metadata)['fixed_revision']!=record['fixed_revision']:
            raise ValueError('Upstream notice source pin/provenance changed')
        required=f'experiment/validation_v7/{record["application_id"]}/source/LICENSE'
        if not any(row['path']==required for row in record['notices']):raise ValueError('Upstream root LICENSE omitted')
        seen=set();prefix=f'experiment/validation_v7/{record["application_id"]}/source/'
        for notice in record['notices']:
            name=safe_member(notice['path']);raw=read_bytes(name)
            if name!=prefix+safe_member(notice['repository_relative_path']) or name in seen:raise ValueError('Duplicate or foreign upstream notice path')
            seen.add(name)
            if name not in entries or sha_bytes(raw)!=notice['sha256'] or len(raw)!=notice['bytes'] or notice.get('notice_bytes_rewritten') is not False:
                raise ValueError('Original upstream notice bytes changed')
            relation=notice['checkout_to_pinned_relation']
            if relation not in {'byte_identical','CRLF_checkout_matches_LF_pinned_object'}:raise ValueError('Unknown upstream checkout relation')
            pinned=raw if relation=='byte_identical' else raw.replace(b'\r\n',b'\n')
            if (len(pinned)!=notice['pinned_object_bytes'] or sha_bytes(pinned)!=notice['pinned_object_sha256']
                    or hashlib.sha1(b'blob '+str(len(pinned)).encode()+b'\0'+pinned).hexdigest()!=notice['pinned_git_blob_sha1']):
                raise ValueError('Preserved notice/pinned-object commitments disagree')
            count+=1
    return count


def inventory(root,run_dir,*,require_final=False):
    root=Path(root).resolve();run_dir=Path(run_dir).resolve()
    if not run_dir.is_relative_to(root/'experiment/runs') or not run_dir.is_dir():
        raise ValueError('Existing campaign must remain under this workspace experiment/runs')
    if require_final:
        for file in (root/REPORT,run_dir/'FINAL_ACCOUNTING_AND_CLEANUP.json'):
            if not file.is_file():raise ValueError('Final report/accounting/owned cleanup required before create')
        final=read_json(run_dir/'FINAL_ACCOUNTING_AND_CLEANUP.json')
        if final.get('all_owned_helpers_closed') is not True:
            raise ValueError('Evidence cannot be packaged as final while owned helpers remain active')
        if final.get('results_report_sha256')!=sha_bytes((root/REPORT).read_bytes()):
            raise ValueError('Final receipt does not bind the current results report')
        if (run_dir/'ROOT_DISPATCH_LOCK.json').exists():raise ValueError('A root native dispatch is active')
        active=run_dir/'provider/ACTIVE_ALLOCATION.json'
        if active.is_file() and read_json(active).get('allocation_id')!='CLOSED':
            raise ValueError('An upstream provider allocation remains open')
    selected={};omitted=[];pending=[];external=[]
    def add(path,category):
        path=Path(path);relative=path.relative_to(root).as_posix();reason=exclusion(Path(relative))
        if linked(path):raise ValueError('Linked evidence cannot be packaged: '+relative)
        if reason:
            omitted.append({'path':relative,'reason':reason});return
        if relative in selected:return
        raw=path.read_bytes()
        if len(raw)>MAX_FILE_BYTES:raise ValueError('Oversize public evidence: '+relative)
        issues=secret_issues(raw,path.suffix.casefold())
        if issues:raise ValueError('Public-file scan rejected '+relative+': '+','.join(issues))
        if relative not in selected:
            selected[relative]={'path':relative,'bytes':len(raw),'sha256':sha_bytes(raw),'category':category}
            if path.suffix.casefold() in {'.json','.jsonl'}:pending.append(relative)
    def tree(directory,category):
        for current,dirs,files in os.walk(directory,followlinks=False):
            keep=[]
            for name in sorted(dirs):
                path=Path(current)/name;relative=path.relative_to(root).as_posix()
                if linked(path):raise ValueError('Linked directory cannot be packaged: '+relative)
                if name.casefold() in PRIVATE_PARTS:
                    omitted.append({'path':relative+'/','reason':('Installed source-only projection dependencies; unnecessary for saved native reanalysis; explicit frozen-file references remain fail-closed' if name.casefold()=='component_deps' else 'private/upstream clone/dependency build tree')})
                else:keep.append(name)
            dirs[:]=keep
            for name in sorted(files):add(Path(current)/name,category)
    tree(root/'experiment/development_v8','v8_protocol_code_inputs_and_source_proofs')
    tree(run_dir,'actual_public_campaign_including_all_development_rounds_and_attempts')
    for relative in SUPPORT_FILES:
        file=root/relative
        if not file.is_file():
            if relative==REPORT and not require_final:continue
            raise ValueError('Required support evidence missing: '+relative)
        add(file,'reused_frozen_policy_primary_checkers_or_prior_cost_provenance')
    for app,metadata_name in UPSTREAM_NOTICE_SOURCES.items():
        add(root/'experiment/validation_v7'/app/metadata_name,'pinned_upstream_source_notice_provenance')
    # Close actual frozen source/input/receipt dependencies. No upstream tree is
    # copied just because it exists; only an explicit public binding may add it.
    seen=set()
    while pending:
        name=pending.pop()
        if name in seen:continue
        seen.add(name);file=root/name
        values=json_rows(file) if file.suffix.casefold()=='.jsonl' else [read_json(file)]
        for value in values:
            for recorded,expected in _dependency_pairs(value,name):
                relative=_host_relative(root,recorded);target=root/relative
                if relative==EXTERNAL_PLUGIN:
                    if not target.is_file() or expected is None or sha_bytes(target.read_bytes())!=expected:
                        raise ValueError('Frozen native provider archive dependency changed')
                    declaration={'recorded_path':str(target),'recorded_key':recorded,'sha256':expected,
                        'freeze_document':name,'scope':'Original public native-provider source archive hash checked during packaging; archive bytes not shipped'}
                    if declaration not in external:external.append(declaration)
                    continue
                if not target.is_file():raise ValueError('Required public binding is missing: '+recorded)
                reason=exclusion(Path(relative))
                if reason:raise ValueError('A promised immutable dependency was excluded: '+relative+' ('+reason+')')
                actual=selected[relative]['sha256'] if relative in selected else sha_bytes(target.read_bytes())
                if expected is not None and actual!=expected:
                    raise ValueError('Frozen source/native dependency changed: '+recorded)
                add(target,'explicit_frozen_source_input_or_immutable_receipt_dependency')
    notices=upstream_notice_inventory(root,selected)
    for record in notices:
        for notice in record['notices']:add(root/notice['path'],'original_pinned_upstream_license_or_notice')
    entries=[selected[name] for name in sorted(selected)]
    aliases=[]
    for name in selected:
        if PurePosixPath(name).name not in {'SOURCE_SNAPSHOT.json','QUALIFICATION_FACTORY_SNAPSHOT.json'}:continue
        record=read_json(root/name)
        if record.get('source_sha256')!=record.get('snapshot_sha256'):raise ValueError('Historical source snapshot is not byte-identical')
        target=_host_relative(root,record['snapshot_path'])
        if target not in selected or selected[target]['sha256']!=record['snapshot_sha256']:raise ValueError('Historical source snapshot is missing')
        aliases.append({'recorded_path':record['source_path'],'sha256':record['source_sha256'],'target':target,'provenance':name})
    if sum(row['bytes'] for row in entries)>MAX_TOTAL_BYTES:raise ValueError('Artifact exceeds the public total size limit')
    return {'schema_version':SCHEMA,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'original_workspace_root':str(root),'campaign_relative_path':run_dir.relative_to(root).as_posix(),
        'files':entries,'files_sha256':sha_bytes(canonical(entries)),
        'historical_source_aliases':aliases,'external_dependency_bindings':external,'upstream_source_notices':notices,
        'excluded':sorted(omitted,key=lambda row:row['path']),
        'security':{'recognized_secret_scan_passed':True,'secret_scan_is_exhaustive_attestation':False,
            'receipt_bytes_or_recorded_paths_rewritten':False,'credentials_private_databases_models_images_or_executables_included':False,
            'public_research_allowance_files_included_for_frozen_cap_provenance':True},
        'scope':'Separate development and held-out native workload validation; full comparison and criteria independently recomputed when a complete80-trajectory frame exists.'}


def guide(manifest):
    return ('''# Separate development and held-out workload evidence (v8)

This artifact retains the original two-candidate development failure, its
separately declared one-candidate extension, every fresh qualification/reference
acquisition and all actual main work. Presence of an archive does not establish
CG1 utility: reanalysis computes the frozen criteria from saved observations.

Use a clean extraction, from any working directory:

```
python -I -B <extract>/experiment/development_v8/package.py verify --root <extract>
python -I -B <extract>/experiment/development_v8/package.py reanalyse --root <extract>
```

Reanalysis makes no native, model, Docker or network calls. Every old absolute
Windows path resolves solely through this manifest to the extraction. Replayed
CG1 and baseline decisions use the unchanged extracted evaluator/policy source;
read/sha/rows adapters relocate reads without rewriting evidence or criteria.
No original-workspace reads are needed, even if that workspace still exists.
If the observed-index posthoc sensitivity is present, its three paid OLD proofs
and single-instance/two-cell overlay are rechecked separately. All80 original
and aligned trajectory scores are recomputed through the unchanged evaluator;
the posthoc summary never replaces primary results or supplies new gold.

Private state and credentials, databases, model/executable/image binaries, full
upstream clones and dependency build trees are excluded. Public research cap/
allowance files contain no service credentials and remain for freeze provenance.
Individual explicitly frozen public upstream source files may be included.
Original upstream LICENSE and applicable NOTICE/COPYING texts are retained
verbatim, with checkout-byte hashes and pinned Git-object/source provenance.
Checkout CRLF differences are documented rather than rewritten. These texts
keep their original upstream terms; the artifact introduces no umbrella license.
Formal publication/release license review remains an outstanding author task.
The installed component_deps dependency tree is excluded. No original freeze
or immutable receipt binds files in that tree in this campaign; versions and
source-only projection records remain. Reexecuting those component projections
requires separately installed pinned libraries, rather than unshipped bytes.
The native-provider .difypkg archive has an explicit unshipped hash declaration;
this verifies its preserved commitment, not bytes absent from this extraction.
Reexecuting native applications requires separately acquired pinned dependencies.
Saved-data reanalysis is the supported offline reproduction path.

The earlier 2,071 native units and 9,316.086159400991 allocation seconds are carried
from the included prior finalized receipt; reanalysis does not pretend to rerun
all earlier campaigns. Current-phase costs are reconciled against every current
reservation, root operation and provider boundary.

Freshness concerns new held-out workload instances in the same developed native
applications and historical fault families. These controlled factual workloads
do not establish unseen-application, industrial, semantic-quality or universal
testing-technique guidance. Recognized secret scans are safeguards, not an
exhaustive security attestation.
'''+ '\nCampaign: `'+manifest['campaign_relative_path']+'`.\n').encode('utf-8')


PURE_MODULES=(
 'experiment.native_v3.common.contracts','experiment.native_v3.common.reference',
 'experiment.validation_v7.guidance.policy','experiment.validation_v7.execution.runner',
 'experiment.validation_v7.execution.source_channels','experiment.development_v8.acquisition',
 'experiment.development_v8.execution.runner','experiment.development_v8.protocol.gates',
 'experiment.development_v8.execution.impact',
 'experiment.development_v8.execution.preflight','experiment.development_v8.execution.evaluate',
 'experiment.development_v8.execution.analysis')
SCOPE_FIELDS=('cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256')
SECONDARY_SOURCE='experiment.development_v8.secondary_retestall'
SENSITIVITY_SOURCE='experiment.development_v8.sensitivity_instance_alignment'


@contextlib.contextmanager
def saved_sources(resolver):
    """Import only manifest-bound, extracted pure checkers; relocate all reads.

    Lexical paths deliberately cannot probe the historical filesystem. They
    preserve its strings in the evaluator's returned provenance dictionaries.
    """
    source_names=PURE_MODULES+tuple(name for name in (SECONDARY_SOURCE,SENSITIVITY_SOURCE) if name.replace('.','/')+'.py' in resolver.entries)
    saved={key:value for key,value in sys.modules.items() if key=='experiment' or key.startswith('experiment.')}
    for key in saved:del sys.modules[key]
    pathbase=PureWindowsPath if re.match(r'^[A-Za-z]:',resolver.manifest['original_workspace_root']) else PurePosixPath
    class SavedPath(pathbase):
        def resolve(self,*args,**kwargs):return self
        def read_text(self,encoding='utf-8',**kwargs):return resolver.resolve(str(self)).read_text(encoding=encoding,**kwargs)
        def read_bytes(self):return resolver.resolve(str(self)).read_bytes()
        def is_file(self):
            try:return resolver.relative(str(self)).casefold() in resolver.names
            except ValueError:return False
        def exists(self):
            try:
                name=resolver.relative(str(self)).casefold()
                return name in resolver.names or any(value.startswith(name.rstrip('/')+'/') for value in resolver.names)
            except ValueError:return False
        def glob(self,pattern):
            prefix=resolver.relative(str(self)).rstrip('/')+'/'
            for name in sorted(resolver.entries):
                tail=name[len(prefix):] if name.casefold().startswith(prefix.casefold()) else None
                if tail is not None and tail.count('/')==pattern.count('/') and fnmatch.fnmatchcase(tail,pattern):
                    yield SavedPath(resolver.original(name))
        def rglob(self,pattern):
            prefix=resolver.relative(str(self)).rstrip('/')+'/'
            for name in sorted(resolver.entries):
                if name.casefold().startswith(prefix.casefold()) and fnmatch.fnmatchcase(PurePosixPath(name).name,pattern):
                    yield SavedPath(resolver.original(name))
    def source_sha(recorded):
        try:return sha_bytes(resolver.resolve(str(recorded)).read_bytes())
        except ValueError:
            for declaration in resolver.external:
                if resolver.relative(declaration['recorded_path'])==resolver.relative(str(recorded)):
                    return declaration['sha256']
            raise
    def denied(*args,**kwargs):raise ValueError('Saved-output replay cannot write or dispatch')
    def load(name):
        relative=name.replace('.','/')+'.py';path=resolver.resolve(relative)
        module=types.ModuleType(name);module.__file__=str(path);module.__package__=name.rpartition('.')[0]
        sys.modules[name]=module
        parent,_,child=name.rpartition('.')
        if parent:setattr(sys.modules[parent],child,module)
        exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
        return module
    try:
        packages=sorted({'.'.join(name.split('.')[:i]) for name in source_names for i in range(1,len(name.split('.')))},key=lambda s:(s.count('.'),s))
        for name in packages:
            module=types.ModuleType(name);module.__path__=[str(resolver.root/name.replace('.','/'))];module.__package__=name
            sys.modules[name]=module
            parent,_,child=name.rpartition('.')
            if parent:setattr(sys.modules[parent],child,module)
        loaded={name:load(name) for name in source_names}
        for module in loaded.values():
            if hasattr(module,'read'):module.read=lambda p:read_json(resolver.resolve(str(p)))
            if hasattr(module,'sha'):module.sha=source_sha
            if hasattr(module,'write_new'):module.write_new=denied
            if hasattr(module,'append'):module.append=denied
        for name in ('experiment.development_v8.protocol.gates','experiment.development_v8.execution.preflight','experiment.development_v8.execution.evaluate','experiment.development_v8.execution.analysis'):
            loaded[name].Path=SavedPath
            if hasattr(loaded[name],'ROOT'):loaded[name].ROOT=SavedPath(resolver.manifest['original_workspace_root'])
        impact=loaded['experiment.development_v8.execution.impact'];impact.Path=SavedPath
        impact.ROOT=SavedPath(resolver.manifest['original_workspace_root']);impact.ASSETS=impact.ROOT/'experiment/validation_v7'
        if SECONDARY_SOURCE in loaded:
            loaded[SECONDARY_SOURCE].Path=SavedPath;loaded[SECONDARY_SOURCE].ROOT=SavedPath(resolver.manifest['original_workspace_root'])
        if SENSITIVITY_SOURCE in loaded:
            loaded[SENSITIVITY_SOURCE].Path=SavedPath;loaded[SENSITIVITY_SOURCE].ROOT=SavedPath(resolver.manifest['original_workspace_root'])
        loaded['experiment.development_v8.execution.evaluate'].rows=lambda p:json_rows(resolver.resolve(str(p)))
        for name,module in list(sys.modules.items()):
            if name.startswith('experiment.') and getattr(module,'__file__',None):
                actual=Path(module.__file__).resolve()
                if not actual.is_relative_to(resolver.root):raise ValueError('Pure source imported outside extraction')
                resolver.resolve(actual.relative_to(resolver.root).as_posix())
        yield {name.rsplit('.',1)[-1]:module for name,module in loaded.items()}
    finally:
        for key in list(sys.modules):
            if key=='experiment' or key.startswith('experiment.'):del sys.modules[key]
        sys.modules.update(saved)


def _join(receipt,provider):
    join=receipt['provider_join'];ident=receipt['allocation_id'];ids=join.get('provider_request_ids',[])
    if join.get('joined') is not True:raise ValueError('Unreconciled provider operation')
    rows=[provider[key] for key in ids]
    if len(set(ids))!=len(ids) or any(row.get('allocation_id')!=ident for row in rows):raise ValueError('Provider allocation join mismatch')
    chat=[row for row in rows if row['path']=='/v1/chat/completions'];emb=[row for row in rows if row['path']=='/v1/embeddings']
    if len(chat)!=join['chat_boundary_attempts'] or len(emb)!=join['embedding_boundary_attempts']:raise ValueError('Provider boundary counts differ')
    if not math.isclose(sum(row.get('generate_gpu_allocation_seconds_including_failure',0) for row in chat),join['gpu_allocation_seconds'],abs_tol=1e-6):raise ValueError('Provider generation costs differ')
    if not math.isclose(sum(row.get('embedding_cpu_seconds',0) for row in emb),join['embedding_cpu_seconds_recorded'],abs_tol=1e-6):raise ValueError('Provider embedding costs differ')
    return len(chat),len(emb)


def accounting(resolver,campaign):
    get=lambda suffix:read_json(resolver.resolve(campaign+'/'+suffix))
    ledger=json_rows(resolver.resolve(campaign+'/native_reservations.jsonl'));previous='0'*64;reservations={}
    prior=read_json(resolver.resolve(PRIOR_RECEIPT))
    authority=get('CAMPAIGN_AUTH.json');segment=get('SEGMENT_DECLARATION.json')
    prior_sha=sha_bytes(resolver.resolve(PRIOR_RECEIPT).read_bytes())
    if (authority['prior_cost_record_sha256']!=prior_sha or segment['prior_receipt_sha256']!=prior_sha
            or authority['prior_native_query_units']!=prior['native_units_cumulative']
            or authority['prior_shared_gpu_seconds']!=prior['cumulative_generation_allocation_seconds']
            or authority['native_query_cap']!=2929 or authority['shared_native_query_cap']!=5000
            or authority['shared_gpu_cap_seconds']!=43200):raise ValueError('Prior cost carry-forward or shared authority caps differ')
    authority_sha=sha_bytes(resolver.resolve(campaign+'/CAMPAIGN_AUTH.json').read_bytes())
    for index,row in enumerate(ledger,1):
        body={key:value for key,value in row.items() if key!='sha256'}
        if (row['index']!=index or row['previous_sha256']!=previous or sha_bytes(canonical(body))!=row['sha256']
                or row['request_id'] in reservations or row['global_native_query_units_after']!=prior['native_units_cumulative']+index
                or row['campaign_auth_sha256']!=authority_sha):
            raise ValueError('Native reservation chain/global continuity differs')
        previous=row['sha256'];reservations[row['request_id']]=row
    if get('NATIVE_HEAD.json')!={'index':len(ledger),'sha256':previous}:raise ValueError('Native reservation head differs')
    provider_rows=json_rows(resolver.resolve(campaign+'/provider/requests.jsonl'));provider={row['request_id']:row for row in provider_rows}
    if len(provider)!=len(provider_rows):raise ValueError('Duplicate provider boundary identifier')
    operations={};joined=[]
    for row in json_rows(resolver.resolve(campaign+'/operation_index.jsonl')):
        receipt=read_json(resolver.resolve(row['path'],expected=row['sha256']));ident=row['allocation_id']
        if receipt['allocation_id']!=ident or ident in operations:raise ValueError('Duplicate/foreign root operation')
        operations[ident]=receipt;_join(receipt,provider);joined.extend(receipt['provider_join'].get('provider_request_ids',[]))
    boundary_ids={row['request_id'] for row in provider_rows if row['path'] in ('/v1/chat/completions','/v1/embeddings')}
    if len(joined)!=len(set(joined)) or set(joined)!=boundary_ids:raise ValueError('Provider boundaries duplicated or unjoined')
    for ident,row in reservations.items():
        if operations.get(ident,{}).get('native_reservation')!=row:raise ValueError('Native reservation lacks its exact sealed operation')
    counter=get('provider/COUNTER.json');chat=[row for row in provider_rows if row['path']=='/v1/chat/completions'];emb=[row for row in provider_rows if row['path']=='/v1/embeddings']
    if counter['chat_requests_reserved']!=len(chat) or counter['embedding_requests_started']!=len(emb):raise ValueError('Provider counter/log counts differ')
    measured=sum(row.get('generate_gpu_allocation_seconds_including_failure',0) for row in chat)+sum(row.get('model_setup_gpu_allocation_seconds',0) for row in provider_rows)
    if not math.isclose(measured,counter['gpu_allocation_seconds_accounted'],abs_tol=1e-5):raise ValueError('Generation/startup sum differs from counter')
    scientific=0
    for row in chat:
        metadata=reservations[row['allocation_id']]['metadata']
        if metadata['phase']!='setup_probe':
            scientific+=1
            if row['request'].get('temperature')!=0 or row['request'].get('max_tokens')!=96:raise ValueError('Scientific generation parameters differ')
        if row.get('http_status')==200:
            verbose=row.get('upstream_actual_response',{}).get('__verbose',{});usage=row.get('upstream_usage',{})
            if (row.get('bridge_input_truncation') is not False or verbose.get('truncated') is not False
                    or usage.get('prompt_tokens_details',{}).get('cached_tokens')!=0 or row.get('upstream_request',{}).get('cache_prompt') is not False):
                raise ValueError('Unexpected generation truncation/cache semantics')
    final=get('FINAL_ACCOUNTING_AND_CLEANUP.json');cumulative_native=prior['native_units_cumulative']+len(ledger)
    cumulative_gpu=prior['cumulative_generation_allocation_seconds']+counter['gpu_allocation_seconds_accounted']
    if (final.get('all_owned_helpers_closed') is not True or final['native_units_this_phase']!=len(ledger)
            or final['native_units_cumulative']!=cumulative_native
            or not math.isclose(final['cumulative_generation_allocation_seconds'],cumulative_gpu,abs_tol=1e-5)
            or cumulative_native>5000 or cumulative_gpu>43200):raise ValueError('Final cumulative accounting/closed cleanup differs')
    for name,digest in final.get('evidence',{}).items():resolver.resolve(campaign+'/'+name,expected=digest)
    resolver.resolve(REPORT,expected=final['results_report_sha256'])
    return {'new_native_units':len(ledger),'prior_native_units':prior['native_units_cumulative'],'cumulative_native_units':cumulative_native,
        'phase_native_units':dict(Counter(row['metadata']['phase'] for row in ledger)),
        'root_operations_joined':len(operations),'provider_chat_boundaries':len(chat),'provider_embedding_boundaries':len(emb),
        'scientific_model_parameter_checks':scientific,'current_generation_allocation_seconds':counter['gpu_allocation_seconds_accounted'],
        'prior_generation_allocation_seconds':prior['cumulative_generation_allocation_seconds'],'cumulative_generation_allocation_seconds':cumulative_gpu},reservations,operations


def audit_raw(resolver,raw,reservations,operations):
    ident=raw['request_id'];native=raw['native_output'];receipt=raw['root_meter_receipt'];reservation=reservations.get(ident)
    if receipt.get('native_reservation')!=reservation or reservation is None:raise ValueError('Raw query is not in exact native ledger')
    sealed=operations.get(ident)
    canonical={key:value for key,value in receipt.items() if key!='main_admission_guard'}
    if sealed is None or canonical!=sealed:raise ValueError('Wrapper changed canonical sealed fields or added an undeclared extension')
    if raw['phase'] in ('profile','calibration','comparison'):
        master=read_json(resolver.resolve(resolver.manifest['campaign_relative_path']+'/MAIN_BUDGET_MASTER.json'))
        authority=read_json(resolver.resolve(resolver.manifest['campaign_relative_path']+'/CAMPAIGN_AUTH.json'))
        audit_main_guard(receipt,master,authority)
    elif 'main_admission_guard' in receipt:raise ValueError('A non-main query acquired a main-only receipt extension')
    metadata=reservation['metadata']
    for key in ('request_id','state_id','task_id',*SCOPE_FIELDS):
        if any(row.get(key)!=raw.get(key) for row in (native,metadata)):raise ValueError('Native/wrapper/reservation identity/scope differs')
    if (receipt.get('dispatch_safe_to_continue') is not True or receipt.get('native_query_units_reserved')!=1
            or receipt.get('provider_join',{}).get('joined') is not True or native.get('valid_native_response') is not True):raise ValueError('Native receipt invalid/unjoined')
    original=read_json(resolver.resolve(native['receipt_path'],expected=native.get('receipt_sha256')))
    for key in ('request_id','state_id','task_id','workspace_id','native_response','answer','completed',*SCOPE_FIELDS):
        if original.get(key)!=native.get(key):raise ValueError('Original native payload differs from wrapper')


def audit_main_guard(receipt,master,authority):
    """Authenticate the sole documented post-seal MainBudgetCampaign extension."""
    guard=receipt.get('main_admission_guard');baseline=master['main_start_gpu_allocation_seconds']
    cap=master['whole_remaining_generation_allocation_seconds_ceiling'];reserve=authority['max_native_timeout_seconds']
    before_counter=receipt['started_counter']['gpu_allocation_seconds_accounted']
    after_counter=receipt['finished_counter']['gpu_allocation_seconds_accounted']
    before,after=before_counter-baseline,after_counter-baseline
    remaining=min(cap-after,authority['phase_gpu_cap_seconds']-after_counter,
        authority['shared_gpu_cap_seconds']-authority['prior_shared_gpu_seconds']-after_counter)
    expected={'master_gpu_baseline':baseline,'main_admission_ceiling_seconds':cap,
        'reserved_native_lifetime_seconds':reserve,'actual_main_gpu_seconds_before':before,
        'actual_main_gpu_seconds_after':after,'remaining_main_phase_shared_room':remaining,
        'measured_main_ceiling_overshoot_seconds':max(0.,after-cap),'physical_preemption_guaranteed':False,
        'post_operation_health_error':None,'actual_cost_reconciled':True}
    initial_room=min(cap-before,authority['phase_gpu_cap_seconds']-before_counter,
        authority['shared_gpu_cap_seconds']-authority['prior_shared_gpu_seconds']-before_counter)
    if not isinstance(guard,dict) or set(guard)!=set(expected) or cap!=24000 or reserve!=600 or initial_room<reserve:
        raise ValueError('Missing, unknown or inadmissible main receipt guard')
    for key,value in expected.items():
        actual=guard[key]
        if isinstance(value,float):
            if isinstance(actual,bool) or not isinstance(actual,(float,int)) or not math.isclose(actual,value,abs_tol=1e-6,rel_tol=0):raise ValueError('Main admission guard differs: '+key)
        elif actual!=value or (isinstance(value,bool) and type(actual) is not bool):raise ValueError('Main admission guard differs: '+key)


def acquisitions(resolver,campaign,modules,reservations,operations):
    gates=modules['gates'];contracts_class=modules['source_channels'].CanonicalContracts;result=[]
    completion_paths=sorted(name for name in resolver.entries if name.startswith(campaign+'/') and name.endswith('/meter/REFERENCE_COMPLETION.json'))
    for path in completion_paths:
        completion=read_json(resolver.resolve(path));directory=str(PurePosixPath(path).parent);app=completion['application_id'];cohort=completion['cohort_id'];mode=completion['phase'];prompt=completion['prompt_candidate_id']
        base=f'experiment/development_v8/workloads/{cohort}/{app}'
        input_path=(campaign+'/development_round2/INPUT_FREEZE.json' if mode=='development' and prompt=='P2'
                    else campaign+f'/input_freezes/{cohort}_{app}_{prompt}.json')
        input_file=resolver.resolve(input_path,expected=completion['input_freeze_sha256']);input_document=read_json(input_file)
        if (input_document['cohort_id']!=cohort or input_document['prompt_id']!=prompt
                or input_document['prompt_text_sha256']!=completion['prompt_text_sha256']):raise ValueError('Acquisition scope differs from exact committed input/prompt')
        if cohort=='validation':
            allowed=read_json(resolver.resolve(campaign+'/VALIDATION_FREEZE.json'))['allowed_scope_by_application'][app]
            if any(completion.get(key)!=expected for key,expected in allowed.items()):raise ValueError('Fresh acquisition differs from selected frozen scope')
        spec=read_json(resolver.resolve(base+'/qualification.json'));document=read_json(resolver.resolve(base+'/contracts.json'))
        gate=gates.gate_saved_acquisition(resolver.original(directory),application_id=app,cohort_id=cohort,prompt_id=prompt,
            prompt_text_sha256=completion['prompt_text_sha256'],input_freeze_sha256=completion['input_freeze_sha256'],mode=mode,
            task_ids=spec['task_ids'],contract_document=document,witnesses=spec['qualification_witnesses'],
            controls={state:spec['unaffected_controls'] for state in ('A_BAD','B_BAD')},bad_subsets=spec['qualification_subsets'])
        contracts=contracts_class(document);bank=json_rows(resolver.resolve(directory+'/sealed/reference_outputs.jsonl'));source_passes=0
        for row in bank:
            raw=read_json(resolver.resolve(row['receipt_path'],expected=row['receipt_sha256']));audit_raw(resolver,raw,reservations,operations)
            checked=contracts.check(raw['task_id'],raw['native_output'],bindings=raw['native_output']['source_bindings'],state=raw['state_id'],reference=True)
            if any(checked[key]!=row['reference_check'][key] for key in ('primary_pass','source_metadata_pass')):raise ValueError('Saved canonical primary/source judgment differs')
            source_passes+=checked['source_metadata_pass']
        saved_gate=directory.rsplit('/meter',1)[0]+'/ADMISSION_GATE.json'
        if saved_gate in resolver.entries:
            saved=read_json(resolver.resolve(saved_gate))
            if gate!=saved:raise ValueError('Independent development/admission gate differs from saved decision')
        result.append({'directory':directory,'application_id':app,'cohort_id':cohort,'mode':mode,'prompt_id':prompt,
            'gate_passed':gate['passed'],'outputs':gate['outputs'],'healthy_primary_passes':gate['healthy_primary_passes'],
            'primary_passes':gate['primary_passes'],'source_metadata_passes':source_passes,'violated_conditions':gate['violated_conditions'],'gate':gate})
    return result


def development_selection(resolver,campaign,modules,acquired):
    gates=modules['gates'];by={(row['application_id'],row['prompt_id']):row['gate'] for row in acquired if row['mode']=='development'}
    first={app:gates.select_development_candidate({prompt:by[app,prompt] for prompt in ('P0','P1')},application_id=app,cohort_id='development') for app in ('openwebui','dify')}
    closed=read_json(resolver.resolve(campaign+'/DEVELOPMENT_SELECTION.json'))
    if closed['selection_by_application']!=first or closed['status']!='STOP_NO_ELIGIBLE_DEVELOPMENT_CONFIGURATION':raise ValueError('Original closed development failure not retained')
    round2=read_json(resolver.resolve(campaign+'/development_round2/ROUND2_FREEZE.json'))
    if (round2['round1_closed_decision_sha256']!=sha_bytes(resolver.resolve(campaign+'/DEVELOPMENT_SELECTION.json').read_bytes())
            or round2['additional_candidate_order']!=['P2'] or round2['additional_native_questions']!=48
            or round2['fresh_validation_answers_before_extension']!=0 or round2['policy_outcomes_before_extension']!=0
            or round2['original_two_candidate_protocol_adherence_claimed'] is not False):raise ValueError('Adaptive extension declaration differs')
    selected={app:first[app]['selected_prompt_id'] for app in first}
    if selected['dify'] is None and by['dify','P2']['passed']:selected['dify']='P2'
    final=read_json(resolver.resolve(campaign+'/DEVELOPMENT_FINAL_SELECTION.json'));freeze=read_json(resolver.resolve(campaign+'/VALIDATION_FREEZE.json'))
    if final['selected_prompt_by_application']!=selected or freeze['selected_prompt_by_application']!=selected:raise ValueError('Frozen selected configurations disagree with independent eligibility')
    if freeze['validation_answers_before_freeze']!=0 or freeze['policy_decisions_before_freeze']!=0:raise ValueError('Validation was not locked before outputs')
    devfreeze=read_json(resolver.resolve(campaign+'/DEVELOPMENT_FREEZE.json'))
    thresholds={'development':devfreeze['frozen_at_utc'],'P2':round2['declared_at_utc'] if 'declared_at_utc' in round2 else round2.get('frozen_at_utc'),
                'validation':freeze['frozen_at_utc']}
    for reservation in json_rows(resolver.resolve(campaign+'/native_reservations.jsonl')):
        meta=reservation['metadata'];kind='validation' if meta.get('cohort_id')=='validation' else 'P2' if meta.get('prompt_candidate_id')=='P2' else 'development'
        if thresholds[kind] and datetime.fromisoformat(reservation['reserved_at_utc'])<datetime.fromisoformat(thresholds[kind]):raise ValueError('Native answer reservation predates its committed phase declaration')
    return {'original_round1_status':closed['status'],'adaptive_one_candidate_extension_retained':True,'selected_prompt_by_application':selected,
        'both_development_rounds_independently_rechecked':True,'new_native_or_model_queries':0}


def replay_main(resolver,campaign,modules,acquired,reservations,operations):
    frozen=modules['evaluate'];analysis=modules['analysis'];runner=modules['runner'];source=modules['source_channels'];policy=modules['policy']
    # ``runner`` is the final v8 runner in the name-keyed module dictionary.
    applications={};contracts={}
    index_path=campaign+'/preflight/PREFLIGHT_INDEX.json'
    modules['preflight'].refresh_preflight(resolver.original(index_path),resolver.original(campaign+'/VALIDATION_FREEZE.json'))
    cases={app:modules['preflight'].load_case(resolver.original(campaign+'/VALIDATION_FREEZE.json'),app) for app in ('openwebui','dify')}
    for app in ('openwebui','dify'):
        contracts[app]=source.CanonicalContracts(read_json(resolver.resolve(f'experiment/development_v8/workloads/validation/{app}/contracts.json')))
        rows=[row for row in acquired if row['application_id']==app and row['mode']=='reference']
        if len(rows)!=1:raise ValueError('One independent complete reference bank per application required')
        truth,cells=frozen.reference_truth(resolver.original(rows[0]['directory']),contracts[app])
        applications[app]={'reference_cells':cells,'reference_cell_counts':dict(Counter(row['classification'] for row in cells)),
                           'state_cell_stability':dict(Counter(row['status'] for row in truth.values()))}
    freeze=read_json(resolver.resolve(campaign+'/VALIDATION_FREEZE.json'));evaluations=[];raw_results=[];paths=[];physical=[];all_ids=set()
    for block in freeze['main_block_order']:
        base=resolver.relative(block['output_dir']);directory=base+'/block';completion_path=directory+'/BLOCK_COMPLETION.json'
        if completion_path not in resolver.entries:return {'complete':False,'reason':'Full four-block frozen comparison is absent','main_trajectories':len(evaluations)}
        completion=read_json(resolver.resolve(completion_path));app=block['application_id'];rep=block['repetition'];meter=base+'/meter'
        if (completion.get('error') is not None or completion.get('completed_trajectories')!=20 or completion.get('planned_trajectories')!=20
                or completion.get('application_id')!=app or completion.get('repetition')!=rep):raise ValueError('Incomplete/foreign comparison block')
        query_paths=sorted(name for name in resolver.entries if name.startswith(meter+'/raw/') and name.endswith('.json'))
        queries=[read_json(resolver.resolve(name)) for name in query_paths]
        query_sources={raw['request_id']:name for raw,name in zip(queries,query_paths)}
        for raw in queries:
            audit_raw(resolver,raw,reservations,operations);analysis.audit_raw_role(raw,application=app,phase=raw['phase'])
            if any(raw.get(key)!=value for key,value in freeze['allowed_scope_by_application'][app].items()):raise ValueError('Main query differs from frozen validation configuration')
            if raw['phase'] not in ('profile','calibration','comparison') or raw['request_id'] in all_ids:raise ValueError('Foreign/duplicate physical main query')
            all_ids.add(raw['request_id'])
        setup_paths=[meter+'/SETUP.json']+sorted(name for name in resolver.entries if name.startswith(meter+'/setup_steps/') and name.endswith('.json'))
        if meter+'/CLEANUP.json' in resolver.entries:setup_paths.append(meter+'/CLEANUP.json')
        actual=runner.usage(queries+[read_json(resolver.resolve(name)) for name in setup_paths])
        if actual!=completion['physical_usage']:raise ValueError('Physical block allocation differs from all raw/setup receipts')
        profile=[row for row in queries if row['phase']=='profile'];counts=Counter((row['state_id'],row['task_id']) for row in profile)
        if len(profile)!=48 or len(counts)!=16 or set(s for s,t in counts)!={'HEALTHY','A_BAD'} or any(n!=3 for n in counts.values()):raise ValueError('Exact paid OLD profile frame differs')
        feature_by_state={}
        for state in ('HEALTHY','A_BAD'):
            feature=read_json(resolver.resolve(directory+'/features/'+state+'.json'));own=[row for row in profile if row['state_id']==state]
            if feature['task_ids']!=cases[app]['task_ids']:raise ValueError('Paid public profile catalog differs from the exact frozen cohort')
            costs=policy.paired_cost_profile({task:[row['elapsed_seconds'] for row in own if row['task_id']==task] for task in contracts[app].specs})
            if costs!=feature['pair_cost_seconds'] or runner.usage(own)!=feature['actual_shared_physical_usage']:raise ValueError('Paid profile costs differ from actual OLD observations')
            attached=[{**row,'receipt_path':resolver.original(query_sources[row['request_id']]),
                       'receipt_sha256':sha_bytes(resolver.resolve(query_sources[row['request_id']]).read_bytes())} for row in own]
            if [runner.profile_feature(row) for row in attached]!=feature['observations']:raise ValueError('Saved predecision feature projection differs from paid OLD raw context')
            feature_by_state[state]=feature
        for episode,state in ((1,'HEALTHY'),(2,'A_BAD'),(3,'HEALTHY')):
            impact_path=directory+f'/impact/{state}-E{episode}.json';saved_impact=read_json(resolver.resolve(impact_path))
            feature=feature_by_state[state];bindings=next(row['native_output']['source_bindings'] for row in profile if row['state_id']==state)
            changed=cases[app]['changed_tokens_by_episode'][episode]
            if (saved_impact['impact']['changed_tokens']!=changed or saved_impact['feature_receipt_sha256']!=sha_bytes(resolver.resolve(directory+'/features/'+state+'.json').read_bytes())):
                raise ValueError('Impact uses different source changes or another paid feature receipt')
            recomputed=modules['impact'].build_impact(feature,bindings,changed,episode)
            if recomputed!=saved_impact['impact']:raise ValueError('Impact admission/source evidence differs from unchanged source recomputation')
            proof_sha=recomputed['evidence_receipt_sha256']
            if not any(name.startswith(base+'/impact_evidence/') and entry['sha256']==proof_sha for name,entry in resolver.entries.items()):raise ValueError('Recomputed impact proof has no exact raw evidence member')
        events=json_rows(resolver.resolve(directory+'/events.jsonl'));closed=set()
        for event in events:
            if event['kind']=='episode_closed' and event.get('episode_index')==1:closed.add(event['trajectory_id'])
            if event['kind']=='old_feature_block_released' and event.get('state_id')=='A_BAD' and (len(closed)!=20 or set(event['closed_episode1'])!=closed):raise ValueError('A_BAD profile release bypassed all20 E1 closures')
        selected=sorted(name for name in resolver.entries if name.startswith(directory+'/trajectories/') and name.endswith('/TRAJECTORY_RESULT.json'))
        if len(selected)!=20:raise ValueError('Incomplete comparison trajectory frame')
        for name in selected:
            raw=read_json(resolver.resolve(name))
            if (raw['application_id'],raw['repetition'])!=(app,rep):raise ValueError('Foreign main trajectory owner')
            if raw['changed_tokens_by_episode']!={str(episode):tokens for episode,tokens in cases[app]['changed_tokens_by_episode'].items()}:raise ValueError('Trajectory changed source tokens differ from actual frozen cases')
            original=resolver.original(name);evaluations.append(frozen.evaluate_trajectory(original,contracts[app],applications[app]['reference_cells']));raw_results.append(raw);paths.append(original)
        physical.append({'application_id':app,'repetition':rep,'block_completion_path':resolver.original(completion_path),
            'block_completion_sha256':sha_bytes(resolver.resolve(completion_path).read_bytes()),'meter_dir':resolver.original(meter),
            'query_receipt_count':len(queries),'actual_physical_usage':actual,'all_profile_setup_and_own_costs_independently_reconciled':True})
    summary=analysis.summarize(applications,evaluations,raw_results,paths)
    summary.update({'validation_freeze_sha256':sha_bytes(resolver.resolve(campaign+'/VALIDATION_FREEZE.json').read_bytes()),
        'preflight_index_sha256':sha_bytes(resolver.resolve(index_path).read_bytes()),
        'physical_block_usage':physical,'same_retention_and_utility_formulas_as_v7':True,'standalone_allocations_not_summed_as_physical_work':True,
        'freshness_scope':'Fresh workloads in the same developed applications and historical fault families'})
    comparisons=[]
    for name in resolver.entries:
        if name.startswith(campaign+'/') and name.endswith('/SUMMARY.json'):
            reported=read_json(resolver.resolve(name))
            if reported.get('phase')=='EXTERNAL_V8' and 'matched_strata' in reported and 'physical_block_usage' in reported:
                for key,value in summary.items():
                    observed=reported.get(key)
                    if key=='trajectories':
                        observed={row['trajectory_id']:row for row in observed};value={row['trajectory_id']:row for row in value}
                    if observed!=value:raise ValueError('Reported summary differs from unchanged extracted source replay: '+key)
                if 'preflight_index_sha256' in reported:
                    if reported['preflight_index_sha256'] not in {row['sha256'] for row in resolver.entries.values()}:raise ValueError('Reported preflight hash is not manifest-bound')
                comparisons.append(name)
    if len(comparisons)!=1:raise ValueError('One canonical complete v8 analysis summary is required')
    return {'complete':summary['complete_frozen_frame'],'main_trajectories':len(evaluations),'matched_strata':summary['matched_strata'],
        'prospective_directional_retention':summary['prospective_directional_retention'],'prospective_selection_utility':summary['prospective_selection_utility'],
        'family_specific_loss_present':summary['family_specific_loss_present'],'interpretation':summary['interpretation'],
        'reported_summary_matches_independent_source_replay':True,'summary_path':comparisons[0],
        'raw_primary_reference_history_decisions_rankings_deadlines_and_costs_rechecked':True,'source_files_executed':list(PURE_MODULES)}


def replay_secondary(resolver,campaign,modules,acquired,reservations,operations,primary):
    registration_path=campaign+'/SECONDARY_RETESTALL_REGISTRATION.json'
    if registration_path not in resolver.entries:
        if any(row['metadata']['phase']=='secondary_retestall' for row in reservations.values()):raise ValueError('Unregistered secondary native work')
        return {'present':False,'counts_toward_primary_80':False}
    if not primary.get('complete') or primary.get('main_trajectories')!=80:raise ValueError('Secondary diagnostic cannot replace an incomplete primary frame')
    source=modules['secondary_retestall'];registration=read_json(resolver.resolve(registration_path))
    registration_sha=sha_bytes(resolver.resolve(registration_path).read_bytes());attribution=registration.get('attribution',{})
    if (registration.get('diagnostic_id')!=source.DIAGNOSTIC or registration.get('phase')!=source.PHASE
            or registration.get('total_query_cap')!=192 or registration.get('query_cap_per_block')!=48
            or registration.get('generation_allocation_ceiling_seconds')!=2400
            or registration.get('native_lifetime_admission_reserve_seconds')!=600
            or any(attribution.get(key) is not value for key,value in source.ATTRIBUTION.items())):
        raise ValueError('Secondary diagnostic attribution, fixed frame or caps changed')
    code_path=SECONDARY_SOURCE.replace('.','/')+'.py'
    code_sha=sha_bytes(resolver.resolve(code_path).read_bytes())
    if not any(resolver.relative(name)==code_path and digest==code_sha for name,digest in registration.get('files_sha256',{}).items()):raise ValueError('Secondary source was not bound before its own observations')
    freeze=read_json(resolver.resolve(campaign+'/VALIDATION_FREEZE.json'))
    if registration['validation_freeze_sha256']!=sha_bytes(resolver.resolve(campaign+'/VALIDATION_FREEZE.json').read_bytes()):raise ValueError('Secondary changed the primary validation commitment')
    source.require_closed_primary(resolver.original(campaign),freeze,read_json=lambda path:read_json(resolver.resolve(str(path))))
    slots=registration['block_order']
    if [(row['app'],row['repetition']) for row in slots]!=list(source.ORDER):raise ValueError('Secondary application/repetition slots changed')
    reference={}
    for app in ('openwebui','dify'):
        bank=next(row for row in acquired if row['application_id']==app and row['mode']=='reference')
        contracts=modules['source_channels'].CanonicalContracts(read_json(resolver.resolve(f'experiment/development_v8/workloads/validation/{app}/contracts.json')))
        _,cells=modules['evaluate'].reference_truth(resolver.original(bank['directory']),contracts)
        reference[app]={(row['episode_index'],row['task_id']):row['classification'] for row in cells}
    baseline_path=campaign+'/SECONDARY_BASELINE.json';baseline=read_json(resolver.resolve(baseline_path));baseline_sha=sha_bytes(resolver.resolve(baseline_path).read_bytes())
    master=read_json(resolver.resolve(campaign+'/MAIN_BUDGET_MASTER.json'))
    main_units=sum(read_json(resolver.resolve(resolver.relative(row['output_dir'])+'/block/BLOCK_COMPLETION.json'))['physical_usage']['native_query_units'] for row in freeze['main_block_order'])
    if baseline['native_ledger_entries']!=master['main_start_native_ledger_entries']+main_units:raise ValueError('Secondary baseline omitted or reset physical primary work')
    latest_primary=max(datetime.fromisoformat(read_json(resolver.resolve(resolver.relative(row['output_dir'])+'/DRIVER_COMPLETION.json'))['finished_at_utc']) for row in freeze['main_block_order'])
    results=[];all_ids=set();source_models={};verified_bindings=set()
    for ordinal,slot in enumerate(slots):
        app,rep=slot['app'],slot['repetition'];directory=resolver.relative(slot['output_dir'])
        if directory!=campaign+f'/secondary-retestall-{app}-r{rep}':raise ValueError('Secondary output is outside its fixed slot')
        completion=read_json(resolver.resolve(directory+'/SECONDARY_COMPLETION.json'))
        if completion['registration_sha256']!=registration_sha or completion.get('attribution')!=attribution:raise ValueError('Secondary completion changed its declared attribution')
        budget=read_json(resolver.resolve(directory+'/SECONDARY_BUDGET_SELECTION.json'))
        if (budget['registration_sha256']!=registration_sha or budget['baseline_sha256']!=baseline_sha
                or budget['slot_index']!=ordinal or budget['started_native_ledger_entries']!=baseline['native_ledger_entries']+48*ordinal
                or budget['remaining_frame_native_queries']!=48*(4-ordinal)
                or budget['generation_allocation_ceiling_seconds']!=2400 or budget['full_native_lifetime_reserve_seconds']!=600
                or budget['physical_preemption_guaranteed'] is not False):raise ValueError('Secondary slot budget does not preserve the fixed cumulative frame')
        saved=source.evaluate_saved(resolver.original(directory),read_json=lambda path:read_json(resolver.resolve(str(path))),
            sha_file=lambda path:sha_bytes(resolver.resolve(str(path)).read_bytes()),resolve_path=lambda path:source.Path(str(path)))
        if (saved['application_id'],saved['repetition'])!=(app,rep) or saved.get('counts_toward_primary_80') is not False or saved.get('K_budget_matched') is not False:raise ValueError('Secondary was confused with a primary policy trajectory')
        meter=directory+'/meter';raw_paths=sorted(name for name in resolver.entries if name.startswith(meter+'/raw/') and name.endswith('.json'))
        raw_rows=[read_json(resolver.resolve(name)) for name in raw_paths]
        if len(raw_rows)!=48:raise ValueError('Exactly48 separately paid secondary queries required per block')
        for raw in raw_rows:
            audit_raw(resolver,raw,reservations,operations)
            if (raw['phase']!=source.PHASE or raw['application_id']!=app or raw['repetition']!=rep
                    or raw['request_id'] in all_ids or any(raw.get(key)!=value for key,value in freeze['allowed_scope_by_application'][app].items())):
                raise ValueError('Secondary query is reused, foreign or from another selected scope')
            all_ids.add(raw['request_id'])
            reserved=datetime.fromisoformat(reservations[raw['request_id']]['reserved_at_utc'])
            if reserved<datetime.fromisoformat(registration['declared_at_utc']) or reserved<latest_primary:raise ValueError('Secondary answer predates its declaration or closed primary frame')
            state=raw['state_id'];model_key=app,state
            if model_key not in source_models:source_models[model_key]=modules['impact']._source_model(app,state)
            bindings=raw['native_output']['source_bindings']
            id_key='native_file_id' if app=='openwebui' else 'native_document_id'
            if len(bindings)!=8 or len({binding.get(id_key) for binding in bindings})!=8:raise ValueError('Secondary native upload binding catalog differs')
            for binding in bindings:
                key=(app,state,modules['policy'].digest(binding))
                if key not in verified_bindings:
                    if not modules['impact']._binding_valid(binding,app,state,source_models[model_key]):raise ValueError('Secondary production-source/index binding proof differs')
                    verified_bindings.add(key)
        indices=sorted(reservations[raw['request_id']]['index'] for raw in raw_rows)
        first_index=baseline['native_ledger_entries']+48*ordinal+1
        if indices!=list(range(first_index,first_index+48)):raise ValueError('Secondary blocks changed the fixed dispatch order or interleaved undeclared native work')
        first_counter=min(raw['root_meter_receipt']['started_counter']['gpu_allocation_seconds_accounted'] for raw in raw_rows)
        if not math.isclose(budget['started_gpu_allocation_seconds'],first_counter,abs_tol=1e-6,rel_tol=0):raise ValueError('Secondary slot startup GPU baseline differs from actual native work')
        operation_paths=[meter+'/SETUP.json']+sorted(name for name in resolver.entries if name.startswith(meter+'/setup_steps/') and name.endswith('.json'))
        if meter+'/CLEANUP.json' in resolver.entries:operation_paths.append(meter+'/CLEANUP.json')
        physical=modules['runner'].usage(raw_rows+[read_json(resolver.resolve(name)) for name in operation_paths])
        if physical!=completion['physical_usage']:raise ValueError('Secondary costs differ from all actual raw/setup operations')
        expected=reference[app];targets={key for key,label in expected.items() if label=='regression'}
        alarms={(row['episode_index'],row['task_id']) for row in saved['pairs'] if row['unrestricted_alarm']}
        results.append({'application_id':app,'repetition':rep,'native_queries':48,'pairs':24,
            'detected':len(targets&alarms),'missed':len(targets-alarms),'credited_alarms':len(alarms),
            'reference_discordant_alarms':sum(expected[key] not in ('regression','uncertain','incomplete') for key in alarms),
            'repair_alarms':sum(expected[key]=='repair' for key in alarms),'physical_usage':physical,
            'unrestricted_pairs_without_K_ceiling_or_policy_deadline':True})
    physical_ids={row['request_id'] for row in reservations.values() if row['metadata']['phase']==source.PHASE}
    if len(all_ids)!=192 or all_ids!=physical_ids:raise ValueError('Secondary192-query frame does not equal actual native ledger work')
    before=[row for row in reservations.values() if row['index']<=baseline['native_ledger_entries']]
    if baseline['registration_sha256']!=registration_sha or len(before)!=baseline['native_ledger_entries'] or any(row['metadata']['phase']==source.PHASE for row in before):raise ValueError('Secondary baseline overwrote earlier costs')
    counter=read_json(resolver.resolve(campaign+'/provider/COUNTER.json'));actual_gpu=counter['gpu_allocation_seconds_accounted']-baseline['gpu_allocation_seconds']
    if actual_gpu<0 or actual_gpu>registration['generation_allocation_ceiling_seconds']:raise ValueError('Complete secondary exceeded or reset its declared generation ceiling')
    return {'present':True,'complete':True,'secondary_blocks':4,'unique_native_queries':192,
        'registration_sha256':registration_sha,'source_sha256':code_sha,'attribution':attribution,'blocks':results,
        'generation_allocation_seconds_after_secondary_baseline':actual_gpu,
        'counts_toward_primary_80':False,'K_budget_matched':False,'cannot_rescue_primary_result':True,
        'no_secondary_outcomes_entered_primary_policy_or_criteria':True,'new_native_or_model_calls':0}


def replay_sensitivity(resolver,campaign,modules,primary):
    """Recompute optional posthoc labels separately; never replace primary."""
    directory=campaign+'/evaluation/sensitivity-instance-alignment';summary_path=directory+'/SUMMARY.json'
    if summary_path not in resolver.entries:return {'present':False,'primary_replaced':False}
    if not primary.get('complete') or primary.get('main_trajectories')!=80:raise ValueError('Posthoc sensitivity cannot rescue an incomplete primary frame')
    source=modules['sensitivity_instance_alignment'];saved=read_json(resolver.resolve(summary_path))
    code_path=SENSITIVITY_SOURCE.replace('.','/')+'.py';code_sha=sha_bytes(resolver.resolve(code_path).read_bytes())
    original_path=campaign+'/evaluation/SUMMARY.json';original=read_json(resolver.resolve(original_path))
    original_sha=sha_bytes(resolver.resolve(original_path).read_bytes())
    if (saved.get('analysis')!='POSTHOC_OBSERVED_NATIVE_INDEX_STATE_ALIGNMENT'
            or saved.get('primary_analysis_unchanged') is not True
            or saved.get('rescue_or_replacement_of_primary_analysis') is not False
            or saved.get('classification_is_posthoc_sensitivity_not_original_reference_truth') is not True
            or saved.get('primary_summary_sha256')!=original_sha
            or saved.get('analysis_source_sha256')!=code_sha
            or saved.get('new_native_or_provider_queries')!=0):raise ValueError('Posthoc sensitivity lost its source/primary/interpretation commitments')
    if (source.TARGET!={'application_id':'openwebui','repetition':2,'task_id':'VOW07','state_id':'A_BAD'}
            or source.OVERRIDES!={1:'regression',2:'repair'}
            or saved['assumption'].get('target')!=source.TARGET
            or saved['assumption'].get('only_reference_label_overrides')!={'E1':'preserved_correct -> regression','E2':'preserved_correct -> repair'}
            or saved['assumption'].get('E3_and_all_other_cells')!='unchanged'
            or saved['assumption'].get('alternative_oracle_experiment') is not False
            or saved['assumption'].get('policy_inputs_or_history_recomputed_from_reference_labels') is not False):
        raise ValueError('Posthoc sensitivity changed its single-instance assumption')
    for name,digest in saved['source_files_sha256'].items():resolver.resolve(name,expected=digest)
    for name,digest in saved['contract_files_sha256'].items():resolver.resolve(name,expected=digest)
    resolver.resolve(campaign+'/VALIDATION_FREEZE.json',expected=saved['validation_freeze_sha256'])
    contracts={app:modules['source_channels'].CanonicalContracts(read_json(resolver.resolve(
        f'experiment/development_v8/workloads/validation/{app}/contracts.json'))) for app in ('openwebui','dify')}
    evidence=source.verify_override_evidence(resolver.original(campaign+'/audits/OPENWEBUI_REFERENCE_MISMATCH_FORENSICS.json'),
        resolver.original(original_path),contracts['openwebui'])
    if evidence!=saved['override_evidence']:raise ValueError('Sensitivity OLD/native/forensic proof reconstruction differs')
    original_by_id={row['trajectory_id']:row for row in original['trajectories']};before=[];after=[];labels={}
    if saved['original_input_result_sha256']!=original['input_result_sha256']:raise ValueError('Posthoc sensitivity selected another primary trajectory set')
    for recorded,digest in original['input_result_sha256'].items():
        raw=read_json(resolver.resolve(recorded,expected=digest));app,rep=raw['application_id'],raw['repetition']
        cells=original['applications'][app]['reference_cells']
        initial=modules['evaluate'].evaluate_trajectory(recorded,contracts[app],cells)
        if initial!=original_by_id[raw['trajectory_id']]:raise ValueError('Posthoc replay failed to reproduce the separate original primary score')
        before.append(initial);aligned=source.aligned_cells(cells,app,rep);labels[f'{app}-r{rep}']=aligned
        after.append(modules['evaluate'].evaluate_trajectory(recorded,contracts[app],aligned))
    if len(after)!=80 or len({row['trajectory_id'] for row in after})!=80:raise ValueError('Posthoc sensitivity dropped or duplicated a primary trajectory')
    strata=modules['evaluate'].matched_strata(after)
    if len(strata)!=8 or not all(row['complete'] for row in strata):raise ValueError('Posthoc sensitivity has an incomplete matched frame')
    retention=all(row['directional_retention'] for row in strata)
    utility=retention and any(row['strict_selection_utility_before_retention_gate'] for row in strata)
    expected={'trajectory_count':80,'original_totals_independently_reproduced':source.totals(before),
        'sensitivity_totals':source.totals(after),'matched_strata':strata,
        'prospective_formula_retention_under_posthoc_assumption':retention,
        'prospective_formula_utility_under_posthoc_assumption':utility,
        'original_retention':original['prospective_directional_retention'],'original_utility':original['prospective_selection_utility'],
        'qualitative_retention_or_utility_conclusion_changed':retention!=original['prospective_directional_retention'] or utility!=original['prospective_selection_utility'],
        'family_specific_loss_vs_always_combined':any(row['family_specific_losses_must_not_be_hidden_by_aggregate_gain'] for row in strata)}
    if any(saved.get(key)!=value for key,value in expected.items()):raise ValueError('Posthoc summary differs from unchanged source recomputation')
    stored=read_json(resolver.resolve(directory+'/TRAJECTORY_EVALUATIONS.json'))
    if (len(stored)!=80 or len({row['trajectory_id'] for row in stored})!=80
            or {row['trajectory_id']:row for row in stored}!={row['trajectory_id']:row for row in after}):raise ValueError('Posthoc trajectory scores differ from independent replay')
    if labels!=read_json(resolver.resolve(directory+'/REFERENCE_CELLS_BY_INSTANCE.json')):raise ValueError('Posthoc label overlay differs from its declared two-cell change')
    return {'present':True,'posthoc':True,'primary_replaced':False,'new_gold_or_population_accuracy_estimate':False,
        'summary_path':summary_path,'summary_sha256':sha_bytes(resolver.resolve(summary_path).read_bytes()),
        'source_sha256':code_sha,'forensic_receipt_sha256':evidence['forensic_receipt_sha256'],
        'paid_OLD_profile_proofs_rechecked':len(evidence['paid_OLD_profile_proofs']),
        'original_and_aligned_all80_scores_separately_recomputed':True,**expected,'new_native_or_model_calls':0}


def reanalyse(root):
    manifest,resolver,binding_count=verify_tree(root);campaign=manifest['campaign_relative_path']
    resolver.resolve('experiment/validation_v7/guidance/policy.py',expected=POLICY_SHA256)
    resolver.resolve('experiment/validation_v7/GUIDANCE_FREEZE.json',expected=GUIDANCE_FREEZE_SHA256)
    costs,reservations,operations=accounting(resolver,campaign)
    with saved_sources(resolver) as modules:
        acquired=acquisitions(resolver,campaign,modules,reservations,operations)
        selection=development_selection(resolver,campaign,modules,acquired)
        qualifications=[row for row in acquired if row['mode']=='qualification']
        passed=len(qualifications)==2 and all(row['gate_passed'] for row in qualifications)
        main=replay_main(resolver,campaign,modules,acquired,reservations,operations) if passed else {'complete':False,'main_trajectories':0,'reason':'A frozen fresh qualification gate failed; no efficacy conclusion'}
        secondary=replay_secondary(resolver,campaign,modules,acquired,reservations,operations,main)
        sensitivity=replay_sensitivity(resolver,campaign,modules,main)
    final=read_json(resolver.resolve(campaign+'/FINAL_ACCOUNTING_AND_CLEANUP.json'))
    if final['main_trajectories_executed']!=main['main_trajectories']:raise ValueError('Final report comparison count differs from independent source replay')
    return {'verified_files':len(manifest['files']),'verified_immutable_source_receipt_bindings':binding_count,
        'retained_upstream_notice_files':sum(len(row['notices']) for row in manifest.get('upstream_source_notices',[])),
        'external_dependency_hash_declarations_not_shipped':len(resolver.external),'accounting':costs,
        'acquisitions':[{key:value for key,value in row.items() if key!='gate'} for row in acquired],
        'development_selection':selection,'fresh_qualification_passed':passed,'main':main,'secondary_retestall':secondary,
        'posthoc_instance_alignment_sensitivity':sensitivity,
        'original_workspace_used':False,'evidence_bytes_or_recorded_paths_modified':False,'new_native_or_model_calls':0}


def create(root,run_dir,target):
    root=Path(root).resolve();target=Path(target).resolve()
    if target.exists():raise FileExistsError('Artifact already exists')
    manifest=inventory(root,run_dir,require_final=True);resolver=Resolver(root,manifest)
    for entry in manifest['files']:
        path=root/entry['path']
        if path.suffix.casefold() in {'.json','.jsonl'}:
            values=json_rows(path) if path.suffix.casefold()=='.jsonl' else [read_json(path)]
            for value in values:frozen_bindings(value,resolver,entry['path'])
    target.parent.mkdir(parents=True,exist_ok=True);created=False
    try:
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            created=True
            for entry in manifest['files']:
                raw=(root/entry['path']).read_bytes()
                if sha_bytes(raw)!=entry['sha256']:raise ValueError('Evidence changed during packaging')
                archive.writestr(entry['path'],raw)
            archive.writestr(MANIFEST,json.dumps(manifest,indent=2).encode()+b'\n');archive.writestr(GUIDE,guide(manifest))
        verify_zip(target)
    except BaseException:
        # Preserve a failed/partial archive as attempt evidence. A retry must
        # use a fresh target (or explicitly archive this attempt) rather than
        # silently replacing scientific packaging evidence.
        raise
    return {'zip':str(target),'sha256':sha_bytes(target.read_bytes()),'files':len(manifest['files']),'bytes':target.stat().st_size,'new_native_or_model_calls':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    for name in ('plan','create'):
        child=commands.add_parser(name);child.add_argument('--run-dir',required=True,type=Path)
        if name=='create':child.add_argument('--zip',required=True,type=Path)
    child=commands.add_parser('verify');group=child.add_mutually_exclusive_group(required=True);group.add_argument('--root',type=Path);group.add_argument('--zip',type=Path)
    child=commands.add_parser('reanalyse');child.add_argument('--root',required=True,type=Path)
    args=parser.parse_args(argv)
    if args.command=='plan':
        manifest=inventory(ROOT,args.run_dir);result={'files':len(manifest['files']),'bytes':sum(row['bytes'] for row in manifest['files']),'excluded':manifest['excluded'],'new_calls':0}
    elif args.command=='create':result=create(ROOT,args.run_dir,args.zip)
    elif args.command=='reanalyse':result=reanalyse(args.root)
    elif args.zip:result={'verified_files':len(verify_zip(args.zip)['files']),'new_calls':0}
    else:
        manifest,_,bindings=verify_tree(args.root);result={'verified_files':len(manifest['files']),'verified_bindings':bindings,'new_calls':0}
    print(json.dumps(result,indent=2));return result

if __name__=='__main__':main()


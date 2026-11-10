"""Manifest-only public v9 evidence packaging and offline reanalysis.

This post-freeze derivative never starts a native application, provider, model,
container or network request. Original scientific files are copied unchanged.
Historical absolute paths remain documentary strings, never read fallbacks.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
PRIMARY_FREEZE_SHA = 'b5b6df9abfe80799509dcb84b3230737c7edbf0b784f988bf081c98b101b1d08'
GUIDANCE_SHA = 'f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989'
MANIFEST = 'ARTIFACT_MANIFEST.json'
GUIDE = 'ARTIFACT_README.md'
SCHEMA = 'transfer-v9-public-artifact-1'
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 50000
CPU_KEYS = frozenset({'decision_cpu_seconds', 'operational_mask_cpu_seconds',
                     'total_allocated_native_wall_plus_controller_cpu_proxy_seconds'})
PUBLIC_PINS = ('experiment/transfer_v9/upstream/vanna-67f1bceda676ef8b5c6acea7c547ce1e5c67b96a',
               'experiment/transfer_v9/upstream/rasa-f3b733a0c1f1ba9a9b20cac806648dbff2c5d467')
PUBLIC_DEPENDENCY_SOURCE = 'experiment/transfer_v9/amendments/rasa_env/pydeps/'
PUBLIC_DEPENDENCY_ARCHIVE = 'experiment/transfer_v9/amendments/rasa_env/downloads/pyTelegramBotAPI-4.7.0.tar.gz'
PRIVATE_PARTS = frozenset({'env', '.venv', 'venv', 'site-packages', 'node_modules', '.git', '.ssh',
                           '__pycache__', '.pytest_cache', 'model_storage', 'sqlite', 'work', 'tmp', 'temp'})
BINARY_SUFFIXES = frozenset({'.gguf', '.safetensors', '.exe', '.dll', '.bin', '.pyc', '.pyo',
                             '.sqlite', '.sqlite3', '.db', '.db3', '.pkl', '.pickle', '.npz', '.npy'})
PUBLIC_SUFFIXES = frozenset({'.py', '.json', '.jsonl', '.md', '.txt', '.csv', '.log', '.yaml', '.yml',
                             '.toml', '.patch', '.diff', '.jinja', '.jinja2', '.sh', '.ps1', '.html', '.ini', '.cfg'})
SECRET_MARKERS = (
    ('private_key', re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('overleaf_credential', re.compile(rb'olp_[A-Za-z0-9]{20,}')),
    ('openai_credential', re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{20,}')),
    ('github_credential', re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})')),
    ('aws_credential', re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}')),
    ('credential_url', re.compile(rb'https?://[^\s/:@]+:[^\s/@]+@')),
)


class ArtifactError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def safe_name(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or value.startswith('/'):
        raise ArtifactError('Unsafe archive path')
    parts = value.split('/')
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{p}{n}' for p in ('com', 'lpt') for n in range(1, 10)}
    if any(part in ('', '.', '..') or part.endswith((' ', '.')) or
           any(char in part for char in '<>"|?*\x00') or part.split('.')[0].lower() in reserved for part in parts):
        raise ArtifactError('Unsafe/nonportable archive path')
    return value


def linked(path):
    path = Path(path)
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def inside(root, relative):
    root = Path(root).resolve()
    relative = safe_name(relative)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if linked(current):
            raise ArtifactError('Linked artifact path is forbidden')
    try:
        current.resolve().relative_to(root)
    except ValueError as exc:
        raise ArtifactError('Artifact path escapes its extraction') from exc
    return current


def public_source(relative, frozen):
    return relative in frozen and (any(relative.startswith(pin + '/') or relative == pin + '.tar.gz' for pin in PUBLIC_PINS)
                                   or relative.startswith(PUBLIC_DEPENDENCY_SOURCE)
                                   or relative == PUBLIC_DEPENDENCY_ARCHIVE)


def exclusion(relative, frozen):
    name = PurePosixPath(relative)
    if public_source(relative, frozen):
        return None  # Exact pinned public upstream fixtures, not user .env/keys.
    if set(part.lower() for part in name.parts) & PRIVATE_PARTS:
        return 'runtime environment/cache/database/model working state'
    if 'handoff' in name.name.lower():
        return 'internal coordination handoff'
    if name.name.lower().startswith('.env') or name.name.lower() in {'credentials.json', 'secrets.json', 'writer_lock.json'}:
        return 'credential/runtime ownership file'
    if name.suffix.lower() in BINARY_SUFFIXES or name.suffix.lower() in {'.key', '.pem', '.p12', '.pfx', '.zip', '.enc'}:
        return 'private/key/model/executable/working archive bytes'
    if name.suffix.lower() not in PUBLIC_SUFFIXES and name.name.lower() not in {'license', 'notice', 'copying'}:
        return 'outside the public evidence allowlist'
    return None


def content_issues(raw, relative, known_public=False):
    issues = [kind for kind, pattern in SECRET_MARKERS if pattern.search(raw)]
    suffix = PurePosixPath(relative).suffix.lower()
    if known_public:
        # Exact upstream source includes JSONC editor configuration. Its bytes
        # remain frozen; it is not scientific JSON requiring strict parsing.
        return issues
    if suffix not in ('.json', '.jsonl'):
        return issues
    try:
        decoded = raw.decode('utf-8-sig')
        values = [json.loads(line) for line in decoded.splitlines() if line.strip()] if suffix == '.jsonl' else [json.loads(decoded)]
    except (ValueError, UnicodeError):
        return issues + ['invalid public JSON']
    # Already-public pinned upstream test fixtures can contain dummy credential
    # fields. Strong credential/private-key markers above are never exempted.
    sensitive = {'apikey', 'apisecret', 'authorization', 'password', 'passwd', 'accesstoken',
                 'refreshtoken', 'clientsecret', 'credential', 'credentials', 'cookie', 'setcookie'}
    placeholders = {'local-only', 'local-study-no-paid-key', '[REDACTED]',
                    'User explicitly requested freezing conditional guidance and validating independent applications'}
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub('[^a-z0-9]', '', key.lower())
                if normalized in sensitive and item not in (None, False, ''):
                    if not isinstance(item, str) or item not in placeholders:
                        issues.append('nonempty credential field: ' + key)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for value in values:
        walk(value)
    return sorted(set(issues))


def freeze_bindings(document):
    files = document.get('files') if isinstance(document, dict) else None
    if not isinstance(files, dict) or not files:
        return {}
    if not all(isinstance(row, dict) and set(('sha256', 'bytes')) <= set(row) for row in files.values()):
        return {}
    return {safe_name(name): {key: row[key] for key in ('sha256', 'bytes')}
            for name, row in files.items()}


def walk_public(directory, root, frozen):
    """Prune runtime trees before enumeration; do not inspect private DB content."""
    for base, directories, filenames in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories if name.lower() not in PRIVATE_PARTS
                           and not linked(Path(base) / name)]
        for filename in filenames:
            path = Path(base) / filename
            relative = path.relative_to(root).as_posix()
            if not linked(path) and exclusion(relative, frozen) is None:
                yield relative, path


def external_declarations(root):
    relative = 'experiment/runs/development_v8_20261101/backend/ASSET_RECHECK.json'
    authority = read(inside(root, relative))
    return [{'recorded_path': row['path'], 'sha256': row['sha256'], 'bytes': row['bytes'],
             'authority': relative, 'authority_field': 'files_verified',
             'verification_scope': 'historical hash commitment only; unshipped asset bytes are not rehashed by this artifact'}
            for row in authority['files_verified']]


def artifact_guide(run_relative, analysis):
    text = f'''# V9 public saved-data evidence

This archive preserves original frozen sources, prospective amendments,
unsuccessful attempts, native/SDK/provider receipts, complete costs and the final
report. The original scientific files are not rewritten for portability.

Verify and reanalyze from a fresh extraction with Python 3.12 (tested 3.12.14):

```text
python -I -B experiment/transfer_v9/artifacts/package.py verify-tree --root .
python -I -B experiment/transfer_v9/artifacts/package.py reanalyze --root . --output <NEW_DIRECTORY_OUTSIDE_EXTRACTION>
```

Study run: `{run_relative}`. Reanalysis makes no model/native/Docker/network
request. It verifies exact manifest/freeze bytes, invokes the packaged independent
read-only native auditor, and recomputes the registered replay and fresh-bank
stability analysis when those were executed. Original host-absolute Vanna method
paths resolve through case/version source bindings; the host paths are never
followed. No original-workspace fallback exists.

Use Python 3.12 for the historical AST commitments; Python 3.13 is not the
verified audit environment. Only these three freshly measured replay controller fields are excluded from
deterministic equality: `decision_cpu_seconds`, `operational_mask_cpu_seconds`,
and `total_allocated_native_wall_plus_controller_cpu_proxy_seconds`. Every other
trajectory, selection, mask, verdict, detection, alarm, recorded native/setup/
checker/feature duration, budget and confirmation result is compared. Original
CPU measurements remain in the unchanged original files. Newly measured CPU
values are written separately outside the extraction with the reanalysis output.

Working SQLite/model storage, Python environments, model weights, runtime
binaries and Docker images are not shipped. External asset hashes are documentary
commitments; absent asset bytes are not claimed verified. Pinned public upstream
source fixtures (including public environment examples, certificates, encrypted
fixtures and source archives) remain exact upstream bytes; they are not user
credentials and are not decrypted. Upstream LICENSE/NOTICE files govern their
own sources; this package does not relicense them.

The artifact verifies this finite study and its stated stopping decisions. It
does not establish broad application-level portability or journal readiness.
'''
    if analysis is None:
        text += '\nThe original study did not reach policy replay; reanalysis preserves that stopping decision and does not invent outcomes.\n'
    return text.encode()


def build(root, run, report, final_receipt, output, *, audit_calls, analysis=None, includes=()):
    """Called only after the root agent seals the report/accounting/cleanup."""
    root, run = Path(root).resolve(), Path(run).resolve()
    run_relative = run.relative_to(root).as_posix()
    safe_name(run_relative)
    if any(run.rglob('WRITER_LOCK.json')):
        raise ArtifactError('Refusing to package an actively written resource ledger')
    primary = run / 'STUDY_FREEZE.json'
    if sha(primary) != PRIMARY_FREEZE_SHA:
        raise ArtifactError('The original prospective study freeze differs')
    report, final_receipt = Path(report).resolve(), Path(final_receipt).resolve()
    report_relative, final_relative = report.relative_to(root).as_posix(), final_receipt.relative_to(root).as_posix()
    seal = read(final_receipt)
    if not any(seal.get(key) == sha(report) for key in ('report_sha256', 'reviewed_report_sha256', 'results_report_sha256')):
        raise ArtifactError('Final receipt does not bind the reviewed report bytes')
    if not any(seal.get(key) is True for key in ('all_owned_helpers_closed', 'all_helpers_closed')):
        raise ArtifactError('Final receipt has not closed all owned helpers')
    freezes = {primary.relative_to(root).as_posix(): read(primary)}
    # New prospective engineering amendments are additional evidence. The
    # original stopped/failed attempt and initial freeze remain unchanged.
    for path in run.rglob('*.json'):
        if 'FREEZE' in path.name.upper():
            obj = read(path)
            if freeze_bindings(obj):
                freezes[path.relative_to(root).as_posix()] = obj
    frozen = {}
    for document in freezes.values():
        for relative, binding in freeze_bindings(document).items():
            if relative in frozen and frozen[relative] != binding:
                raise ArtifactError('Conflicting historical source bytes require preserved versioned paths: ' + relative)
            frozen[relative] = binding
    selected = {}
    for relative, binding in frozen.items():
        path = inside(root, relative)
        if exclusion(relative, frozen):
            raise ArtifactError('Mandatory frozen file is private/unshippable: ' + relative)
        if path.stat().st_size != binding['bytes'] or sha(path) != binding['sha256']:
            raise ArtifactError('A mandatory frozen source changed: ' + relative)
        selected[relative] = path
    for directory in (root / 'experiment/transfer_v9', run):
        selected.update(walk_public(directory, root, frozen))
    for path in (primary, report, final_receipt, *[Path(p).resolve() for p in includes]):
        relative = path.relative_to(root).as_posix()
        if exclusion(relative, frozen):
            raise ArtifactError('Explicit public file is disallowed: ' + relative)
        selected[relative] = path
    if not isinstance(audit_calls, list) or not audit_calls:
        raise ArtifactError('At least one independent closed-stage audit is required')
    for call in audit_calls:
        if safe_name(call['module']) not in selected:
            raise ArtifactError('Independent audit code is absent from public sources')
        safe_name(call['run'])
    if analysis is not None:
        for key in ('bank', 'protocol', 'confirmation', 'replay_module', 'guidance'):
            if analysis.get(key) and safe_name(analysis[key]) not in selected:
                raise ArtifactError('Required replay input/code is absent: ' + key)
        safe_name(analysis['evaluation'])
        for filename in ('SUMMARY.json', 'MATCHED_CELLS.csv', 'CG1_COMPARISONS.json'):
            if analysis['evaluation'] + '/' + filename not in selected:
                raise ArtifactError('A required original replay output is missing: ' + filename)
    guide = artifact_guide(run_relative, analysis)
    entries = {}
    for relative, path in sorted(selected.items()):
        raw = path.read_bytes()
        issues = content_issues(raw, relative, public_source(relative, frozen))
        if issues:
            raise ArtifactError('Public evidence scan failed at ' + relative + ': ' + ', '.join(issues))
        entries[safe_name(relative)] = {'bytes': len(raw), 'sha256': sha_bytes(raw)}
    entries[GUIDE] = {'bytes': len(guide), 'sha256': sha_bytes(guide)}
    if len(entries) > MAX_MEMBERS or sum(row['bytes'] for row in entries.values()) > MAX_TOTAL:
        raise ArtifactError('Public artifact exceeds its file/byte safety envelope')
    manifest = {'schema': SCHEMA, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'study_run': run_relative, 'primary_freeze': primary.relative_to(root).as_posix(),
        'primary_freeze_sha256': PRIMARY_FREEZE_SHA,
        'files': entries, 'files_sha256': sha_bytes(canonical(entries)),
        'freeze_documents': {name: sha(root / name) for name in freezes},
        'reviewed_report': report_relative, 'reviewed_report_sha256': sha(report),
        'final_receipt': final_relative, 'final_receipt_sha256': sha(final_receipt),
        'unshipped_external_assets': external_declarations(root), 'audit_calls': audit_calls,
        'replay': analysis, 'historical_absolute_paths_are_documentary_only': True,
        'original_workspace_fallback_allowed': False,
        'exact_public_upstream_source_pins': list(PUBLIC_PINS),
        'exact_amendment_frozen_dependency_source_paths': [PUBLIC_DEPENDENCY_SOURCE, PUBLIC_DEPENDENCY_ARCHIVE],
        'replay_nondeterministic_cpu_keys_only': sorted(CPU_KEYS),
        'original_recorded_cpu_measurements_preserved': True}
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True, strict_timestamps=False) as archive:
        for relative in sorted(entries):
            if relative == GUIDE:
                archive.writestr(relative, guide)
            else:
                archive.write(selected[relative], relative)
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2, sort_keys=True).encode() + b'\n')
    verify_zip(output)
    return {'output': str(output), 'bytes': output.stat().st_size, 'sha256': sha(output),
            'public_files': len(entries), 'primary_freeze_sha256': PRIMARY_FREEZE_SHA}


def validate_manifest(manifest):
    if manifest.get('schema') != SCHEMA or manifest.get('files_sha256') != sha_bytes(canonical(manifest.get('files'))):
        raise ArtifactError('Invalid artifact manifest/file-list digest')
    entries = manifest['files']
    if not isinstance(entries, dict) or not entries or len(entries) > MAX_MEMBERS:
        raise ArtifactError('Invalid public file inventory')
    if len({safe_name(name).casefold() for name in entries}) != len(entries):
        raise ArtifactError('Duplicate/case-colliding artifact paths')
    for binding in entries.values():
        if (not isinstance(binding, dict) or type(binding.get('bytes')) is not int or not 0 <= binding['bytes'] <= MAX_FILE
                or not re.fullmatch('[0-9a-f]{64}', str(binding.get('sha256', '')))):
            raise ArtifactError('Malformed public file binding')
    if sum(row['bytes'] for row in entries.values()) > MAX_TOTAL:
        raise ArtifactError('Uncompressed artifact exceeds safety envelope')
    return entries


def verify_zip(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [safe_name(member.filename) for member in members]
        if len(names) > MAX_MEMBERS + 1 or len({name.casefold() for name in names}) != len(names):
            raise ArtifactError('Duplicate/oversized ZIP inventory')
        if any(member.is_dir() or stat.S_ISLNK(member.external_attr >> 16) or member.file_size > MAX_FILE for member in members):
            raise ArtifactError('Unsafe ZIP member')
        if sum(member.file_size for member in members) > MAX_TOTAL + MAX_FILE:
            raise ArtifactError('ZIP total exceeds safety envelope')
        if MANIFEST not in names:
            raise ArtifactError('ZIP manifest missing')
        manifest = json.loads(archive.read(MANIFEST))
        entries = validate_manifest(manifest)
        if set(names) != set(entries) | {MANIFEST}:
            raise ArtifactError('ZIP entries differ from public manifest')
        failed_crc = archive.testzip()
        if failed_crc:
            raise ArtifactError('ZIP CRC failure: ' + failed_crc)
        for name, binding in entries.items():
            raw = archive.read(name)
            if len(raw) != binding['bytes'] or sha_bytes(raw) != binding['sha256']:
                raise ArtifactError('ZIP evidence bytes changed: ' + name)
    return manifest


def extract(path, destination):
    manifest = verify_zip(path)
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name in sorted(set(manifest['files']) | {MANIFEST}):
            target = inside(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(archive.read(name))
    verify_tree(destination)
    return {'extraction': str(destination), 'public_files': len(manifest['files'])}


def verify_tree(root):
    root = Path(root).resolve()
    manifest = read(root / MANIFEST)
    entries = validate_manifest(manifest)
    actual = set()
    for path in root.rglob('*'):
        if linked(path):
            raise ArtifactError('Linked extraction path is forbidden')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(entries) | {MANIFEST}:
        raise ArtifactError('Use a clean extraction; members differ from manifest')
    for name, binding in entries.items():
        path = inside(root, name)
        if path.stat().st_size != binding['bytes'] or sha(path) != binding['sha256']:
            raise ArtifactError('Extracted evidence bytes changed: ' + name)
    freeze_count = 0
    for name, expected in manifest['freeze_documents'].items():
        if name not in entries or sha(inside(root, name)) != expected:
            raise ArtifactError('Freeze authority differs from artifact commitment')
        for relative, binding in freeze_bindings(read(inside(root, name))).items():
            if relative not in entries or entries[relative] != {key: binding[key] for key in ('sha256', 'bytes')}:
                raise ArtifactError('Frozen byte absent or different: ' + relative)
            freeze_count += 1
    primary = inside(root, manifest['primary_freeze'])
    if sha(primary) != manifest['primary_freeze_sha256'] or manifest['primary_freeze_sha256'] != PRIMARY_FREEZE_SHA:
        raise ArtifactError('Original primary freeze changed')
    if sha(inside(root, manifest['reviewed_report'])) != manifest['reviewed_report_sha256']:
        raise ArtifactError('Reviewed report changed')
    final_path = inside(root, manifest['final_receipt'])
    if sha(final_path) != manifest['final_receipt_sha256']:
        raise ArtifactError('Final accounting/cleanup receipt changed')
    seal = read(final_path)
    if (not any(seal.get(key) == manifest['reviewed_report_sha256'] for key in
                ('report_sha256', 'reviewed_report_sha256', 'results_report_sha256'))
            or not any(seal.get(key) is True for key in ('all_owned_helpers_closed', 'all_helpers_closed'))):
        raise ArtifactError('Report seal or owned-helper closure is absent')
    # External asset rows are checked against shipped authority metadata only.
    # Their recorded absolute paths are NEVER resolved, read or stat'ed.
    for row in manifest['unshipped_external_assets']:
        authority = read(inside(root, row['authority']))
        if not any(item['path'] == row['recorded_path'] and item['sha256'] == row['sha256'] and item['bytes'] == row['bytes']
                   for item in authority[row['authority_field']]):
            raise ArtifactError('External-asset commitment does not match original metadata')
    return {'manifest': manifest, 'public_files_verified': len(entries), 'frozen_file_bindings_verified': freeze_count,
            'unshipped_asset_bytes_verified': False, 'original_workspace_fallback_used': False}


def normalize_replay_cpu(value):
    if isinstance(value, dict):
        return {key: normalize_replay_cpu(item) for key, item in value.items() if key not in CPU_KEYS}
    if isinstance(value, list):
        return [normalize_replay_cpu(item) for item in value]
    return value


def compare_replay_outputs(original, current):
    original, current = Path(original), Path(current)
    fixed = {'SUMMARY.json', 'MATCHED_CELLS.csv', 'CG1_COMPARISONS.json'}
    if (original / 'SAME_CASE_CONFIRMATION.json').exists():
        fixed.add('SAME_CASE_CONFIRMATION.json')
    old_names = fixed | {path.relative_to(original).as_posix() for path in (original / 'trajectories').glob('*.json')}
    new_names = {path.relative_to(current).as_posix() for path in current.rglob('*') if path.is_file()}
    if old_names != new_names:
        raise ArtifactError('Reanalysis core file identities differ')
    for name in sorted(old_names):
        if name.endswith('.csv'):
            def csv_rows(path):
                with path.open(newline='', encoding='utf-8-sig') as stream:
                    return [{key: value for key, value in row.items() if key not in CPU_KEYS} for row in csv.DictReader(stream)]
            equal = csv_rows(original / name) == csv_rows(current / name)
        else:
            equal = normalize_replay_cpu(read(original / name)) == normalize_replay_cpu(read(current / name))
        if not equal:
            raise ArtifactError('A deterministic outcome/decision/cost changed: ' + name)
    return len(old_names)


def load_module(root, relative, name):
    path = inside(root, relative)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reanalyze(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or output.is_relative_to(root):
        raise ArtifactError('New CPU measurements must be written outside the immutable extraction')
    checked = verify_tree(root)
    manifest = checked['manifest']
    output.mkdir(parents=True, exist_ok=False)
    audits = []
    for index, call in enumerate(manifest['audit_calls']):
        if call['module'] not in manifest['files']:
            raise ArtifactError('Audit module is not manifest-bound')
        module = load_module(root, call['module'], f'v9_offline_native_audit_{index}')
        args = [root, inside(root, call['run'])]
        if call.get('stage') is not None:
            args.append(call['stage'])
        result = getattr(module, call['entry'])(*args)
        if not isinstance(result, dict) or not str(result.get('status', '')).startswith('PASS'):
            raise ArtifactError('Independent offline native audit did not pass')
        audits.append(result)
    replay_files = 0
    analysis = manifest.get('replay')
    if analysis is not None:
        module = load_module(root, analysis['replay_module'], 'v9_offline_original_replay')
        bank_path, protocol_path = inside(root, analysis['bank']), inside(root, analysis['protocol'])
        bank, protocol = read(bank_path), read(protocol_path)
        guidance = module.load_guidance(inside(root, analysis['guidance']))
        result = module.run_factorial(bank, protocol, guidance)
        result['summary']['bank_sha256'] = sha(bank_path)
        result['summary']['protocol_sha256'] = sha(protocol_path)
        if analysis.get('confirmation'):
            confirmation_path = inside(root, analysis['confirmation'])
            result['confirmation'] = module.compare_confirmation(bank, read(confirmation_path), guidance)
            result['summary']['confirmation_bank_sha256'] = sha(confirmation_path)
            result['summary']['same_case_confirmation_record'] = 'SAME_CASE_CONFIRMATION.json'
        module.write_outputs(result, output / 'recomputed-replay')
        replay_files = compare_replay_outputs(inside(root, analysis['evaluation']), output / 'recomputed-replay')
    receipt = {'status': 'PASS_ISOLATED_SAVED_DATA_REANALYSIS', 'at_utc': datetime.now(timezone.utc).isoformat(),
        'primary_freeze_sha256': manifest['primary_freeze_sha256'], 'independent_native_audits': audits,
        'replay_core_output_files_compared': replay_files, 'replay_executed': analysis is not None,
        'nondeterministic_new_cpu_fields_only': sorted(CPU_KEYS),
        'original_recorded_cpu_fields_preserved_in_unchanged_manifest_bound_files': True,
        'all_other_outcomes_decisions_masks_costs_and_confirmation_results_compared': analysis is not None,
        'native_or_model_dispatches': 0, 'original_workspace_fallback_used': False,
        'unshipped_external_asset_bytes_verified': False,
        'public_files_verified': checked['public_files_verified'],
        'frozen_file_bindings_verified': checked['frozen_file_bindings_verified']}
    (output / 'REANALYSIS_VERIFICATION.json').write_bytes(json.dumps(receipt, indent=2, sort_keys=True).encode() + b'\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build_parser = sub.add_parser('build')
    for key in ('root', 'run', 'report', 'final-receipt', 'output', 'audit-spec'):
        build_parser.add_argument('--' + key, type=Path, required=True)
    build_parser.add_argument('--analysis-spec', type=Path)
    build_parser.add_argument('--include', type=Path, action='append', default=[])
    for command in ('verify-zip', 'extract'):
        child = sub.add_parser(command)
        child.add_argument('--zip', type=Path, required=True)
        if command == 'extract':
            child.add_argument('--destination', type=Path, required=True)
    for command in ('verify-tree', 'reanalyze'):
        child = sub.add_parser(command)
        child.add_argument('--root', type=Path, required=True)
        if command == 'reanalyze':
            child.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.root, args.run, args.report, args.final_receipt, args.output,
                       audit_calls=read(args.audit_spec), analysis=read(args.analysis_spec) if args.analysis_spec else None,
                       includes=args.include)
    elif args.command == 'verify-zip':
        manifest = verify_zip(args.zip)
        result = {'status': 'PASS_ZIP_MANIFEST_HASHES_AND_CRC', 'public_files': len(manifest['files'])}
    elif args.command == 'extract':
        result = extract(args.zip, args.destination)
    elif args.command == 'verify-tree':
        result = {key: value for key, value in verify_tree(args.root).items() if key != 'manifest'}
    else:
        result = reanalyze(args.root, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

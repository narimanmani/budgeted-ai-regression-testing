"""Public, dependency-light helpers for the separately registered v9 study."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRIOR = ROOT / 'experiment/runs/development_v8_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json'
GUIDANCE = ROOT / 'experiment/validation_v7/guidance/policy.py'
GUIDANCE_SHA = 'f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989'
PRIOR_SHA = 'c6f1612ee8ce6a72c10020007d0e73d50a4da0ff5dae9d68ca4851520f3b2004'


def utc():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def verify_foundation():
    if sha(GUIDANCE) != GUIDANCE_SHA or sha(PRIOR) != PRIOR_SHA:
        raise RuntimeError('The immutable guidance or prior final receipt changed')
    prior = read(PRIOR)
    if prior['native_units_cumulative'] != 4938 or not prior['all_owned_helpers_closed']:
        raise RuntimeError('Unexpected historical baseline')
    return prior


def freeze(paths, destination, *, role, metadata=None):
    """Exclusive creation; every path must be a file inside this workspace."""
    verify_foundation()
    bindings = {}
    for path in sorted({Path(p).resolve() for p in paths}):
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            raise ValueError('Freeze includes a non-file: ' + relative)
        bindings[relative] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    result = {'schema': 'transfer-v9-byte-freeze-1', 'role': role,
              'at_utc': utc(), 'guidance_sha256': GUIDANCE_SHA,
              'prior_receipt_sha256': PRIOR_SHA, 'files': bindings,
              'formal_external_registration': False, 'metadata': metadata or {}}
    save(destination, result)
    return result


def verify_freeze(path):
    verify_foundation()
    receipt = read(path)
    for relative, binding in receipt['files'].items():
        actual = (ROOT / relative).resolve()
        actual.relative_to(ROOT)
        if not actual.is_file() or actual.stat().st_size != binding['bytes'] or sha(actual) != binding['sha256']:
            raise RuntimeError('Frozen byte changed: ' + relative)
    return receipt

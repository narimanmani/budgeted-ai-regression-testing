"""Single-owner, local-only model client with per-boundary durable accounting."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import time
import types
from urllib.request import build_opener, ProxyHandler

from experiment.transfer_v9.common import ROOT, save, sha, read, utc
from experiment.transfer_v9.runtime.ledger import zeros

ENDPOINT = 'http://127.0.0.1:33009'


def launch_backend(directory, ledger, *, operation_id='model-startup'):
    """Physically recheck pinned assets; no generation probe or warmup."""
    directory = Path(directory)
    directory.mkdir(exist_ok=False, parents=True)
    assets = read(ROOT / 'experiment/runs/development_v8_20261101/backend/ASSET_RECHECK.json')
    for row in assets['files_verified']:
        path = Path(row['path'])
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise RuntimeError('Pinned runtime/model asset changed: ' + str(path))
    if sha(ROOT/'experiment/native_v3/provider_llamacpp/qwen2_5_7b_official.jinja') != assets['template_sha256']:
        raise RuntimeError('Pinned native chat template changed')
    save(directory / 'ASSET_RECHECK.json', {'at_utc': utc(), 'files': assets['files_verified']})
    command = read(ROOT / 'experiment/runs/development_v8_20261101/backend/START_RECEIPT.json')['command'][:]
    command[command.index('--port')+1] = '33009'
    command[command.index('--log-file')+1] = str(directory / 'backend.log')
    command[command.index('--n-predict')+1] = '256'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', 33009))
    requested = {**zeros(), 'generation_allocation_seconds': 90, 'end_to_end_seconds': 90}
    ledger.reserve(operation_id, 'setup', requested, {'command': command, 'generation_queries': 0})
    started = time.perf_counter()
    process = None
    opener = build_opener(ProxyHandler({}))
    try:
        with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        save(directory / 'OWNER.json', {'pid': process.pid, 'command': command, 'started_at_utc': utc(),
                                       'executable_sha256': sha(command[0])})
        while time.perf_counter()-started < 85:
            if process.poll() is not None:
                raise RuntimeError('Local model startup failed')
            try:
                with opener.open(ENDPOINT+'/health', timeout=1) as response:
                    health = json.load(response)
                if health.get('status') == 'ok':
                    break
            except Exception:
                time.sleep(.2)
        else:
            raise RuntimeError('Local model startup timed out')
        elapsed = time.perf_counter()-started
        receipt = {'pid': process.pid, 'ready_at_utc': utc(), 'startup_generation_allocation_seconds': elapsed,
                   'health': health, 'warmup_or_generation_probe': False, 'owner_sha256': sha(directory/'OWNER.json')}
        save(directory / 'READY.json', receipt)
        ledger.settle(operation_id, {**zeros(), 'generation_allocation_seconds': elapsed,
                      'end_to_end_seconds': elapsed}, status='completed', evidence=receipt)
    except BaseException:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
        elapsed = time.perf_counter()-started
        try:
            ledger.settle(operation_id, {**zeros(), 'generation_allocation_seconds': elapsed,
                          'end_to_end_seconds': elapsed}, status='failed', evidence={'pid': None if process is None else process.pid})
        except BaseException:
            pass  # Its original conservative reservation remains charged.
        raise
    return process


class MeteredClient:
    """The native OpenAI_Chat sees a standard client interface, never reference truth."""
    def __init__(self, ledger, directory, *, sdk=None, role='comparison'):
        if sdk is None:
            import httpx
            from openai import OpenAI
            sdk = OpenAI(base_url=ENDPOINT+'/v1', api_key='local-only', max_retries=0,
                         timeout=120, http_client=httpx.Client(trust_env=False, timeout=120))
        self.sdk = sdk
        self.ledger = ledger
        self.role = role
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.parent = None
        self.counter = 0
        self.call_ids = []
        self.pending_failure = False
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def begin(self, operation_id):
        if self.pending_failure or self.parent is not None:
            raise RuntimeError('Previous native/model operation is unresolved')
        self.parent = operation_id
        self.counter = 0
        self.call_ids = []

    def end(self):
        result = self.call_ids[:]
        self.parent = None
        return result

    def create(self, **kwargs):
        if self.parent is None or self.pending_failure:
            raise RuntimeError('Every provider request needs a live metered native operation')
        if self.counter >= 3:
            raise RuntimeError('Three-chat native-operation ceiling reached')
        if kwargs.get('model') != 'tosem-qwen2.5-7b-q4' or kwargs.get('temperature') != 0:
            raise RuntimeError('Frozen model/generation settings changed')
        if kwargs.get('max_tokens') != 256:
            raise RuntimeError('Frozen output ceiling changed')
        self.counter += 1
        ident = f'{self.parent}-chat{self.counter}'
        self.call_ids.append(ident)
        payload = {**kwargs, 'extra_body': {'seed': 20261101, 'cache_prompt': False}}
        self.ledger.reserve(ident, self.role, {**zeros(), 'provider_chat_units': 1,
                            'generation_allocation_seconds': 125},
                            {'parent_native_operation_id': self.parent, 'model': kwargs['model']})
        start = time.perf_counter()
        try:
            save(self.directory / f'{ident}-request.json', {'operation_id': ident, 'parent': self.parent,
                 'at_utc': utc(), 'payload': payload, 'endpoint': ENDPOINT, 'max_retries': 0})
            response = self.sdk.chat.completions.create(**payload)
            elapsed = time.perf_counter()-start
            path = self.directory / f'{ident}-response.json'
            save(path, {'operation_id': ident, 'parent': self.parent, 'at_utc': utc(),
                        'response': response.model_dump(), 'generation_allocation_seconds': elapsed})
            self.ledger.settle(ident, {**zeros(), 'provider_chat_units': 1,
                'generation_allocation_seconds': elapsed}, status='completed',
                evidence={'response_sha256': sha(path), 'parent_native_operation_id': self.parent})
        except BaseException as exc:
            elapsed = time.perf_counter()-start
            self.pending_failure = True
            # An accounting/serialization failure after dispatch is fatal too.
            # A reservation that cannot be settled stays charged at its bound.
            try:
                save(self.directory / f'{ident}-failure.json', {'type': type(exc).__name__, 'message': str(exc),
                     'elapsed_seconds': elapsed, 'unknown_backend_work_blocks_future_dispatch': True,
                     'allocation_is_lower_bound_until_owned_backend_closes': True})
                self.ledger.settle(ident, {**zeros(), 'provider_chat_units': 1,
                    'generation_allocation_seconds': elapsed}, status='failed',
                    evidence={'parent': self.parent, 'unknown_work': True})
            except BaseException:
                pass
            raise
        return response


def close_backend(process, directory):
    """Only stop the Popen handle created in this call; never enumerate other apps."""
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
    save(Path(directory) / 'CLOSED.json', {'at_utc': utc(), 'pid': None if process is None else process.pid,
         'returncode': None if process is None else process.returncode,
         'only_owned_popen_handle_closed': True, 'unrelated_processes_stopped': False})

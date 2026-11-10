"""Serial campaign allocations and append-only native-query reservations.

The provider meter is reused unchanged; its original zero baseline is persisted
across controller processes. A new stage never resets actual counters or clocks.
"""
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import build_opener, ProxyHandler
import hashlib
import importlib.util
import json
import os
import time

ROOT = Path(__file__).resolve().parents[2]
METER = ROOT / 'experiment/native_v3/librechat/history/reference/provider_meter.py'
spec = importlib.util.spec_from_file_location('_pilot_actual_provider_meter', METER)
meter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meter)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def write_new(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def append(path, value):
    with Path(path).open('ab') as stream:
        stream.write(canonical(value) + b'\n'); stream.flush(); os.fsync(stream.fileno())


class Campaign:
    def __init__(self, auth_path, run_dir, stage_auth_path, *, provider_class=None):
        self.auth_path = Path(auth_path).resolve(); self.auth = read(self.auth_path)
        self.stage_path = Path(stage_auth_path).resolve(); self.stage = read(self.stage_path)
        self.run = Path(run_dir).resolve(); self.run.mkdir(parents=True, exist_ok=True)
        if str(self.run) != self.auth['campaign_run_dir']:
            raise RuntimeError('Wrong root campaign directory')
        if self.auth['provider_phase'] != 'EXTERNAL_V8' or self.stage.get('phase') != 'EXTERNAL_V8':
            raise RuntimeError('Wrong pilot phase')
        if self.stage.get('campaign_auth_sha256') != sha(self.auth_path) or self.stage.get('authorized') is not True:
            raise RuntimeError('Stage is not bound to root campaign authorization')
        if self.auth.get('control_source_sha256') != sha(Path(__file__)):
            raise RuntimeError('Campaign controller source changed')
        if self.auth.get('provider_meter_source_sha256') != sha(METER):
            raise RuntimeError('Provider meter source changed')
        if self.auth['shared_native_query_cap'] != 5000 or self.auth['prior_native_query_units'] != 2071:
            raise RuntimeError('Prior/cumulative native query accounting must remain unchanged')
        prior_path = ROOT / 'experiment/runs/validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json'
        prior = read(prior_path)
        if self.auth.get('prior_cost_record_sha256') != sha(prior_path):
            raise RuntimeError('Prior completed campaign receipt changed')
        if prior['native_units_cumulative'] != 2071 or self.auth['prior_shared_gpu_seconds'] != prior['cumulative_generation_allocation_seconds']:
            raise RuntimeError('Previous physical costs must be carried forward exactly')
        if not 0 < self.auth['native_query_cap'] <= 2929:
            raise RuntimeError('Pilot native query envelope exceeded')
        if time.time() >= min(self.auth['expires_at_epoch'], self.stage['expires_at_epoch']):
            raise RuntimeError('Expired campaign/stage')
        for name in ['sealed', 'stages']:
            (self.run / name).mkdir(exist_ok=True)
        self.owner_path = self.run / 'ROOT_DISPATCH_LOCK.json'
        self.owner = {'pid': os.getpid(), 'stage': self.stage['stage_id'], 'stage_auth_sha256': sha(self.stage_path)}
        write_new(self.owner_path, self.owner)
        self.closed = False
        try:
            cls = provider_class or meter.Provider
            self.provider = cls.__new__(cls)
            self.provider.auth = self.auth
            self.provider.run = self.run
            self.provider.state = Path(self.auth['provider_state_dir']).resolve()
            self.provider.opener = build_opener(ProxyHandler({}))
            health = self.provider.health()
            baseline_path = self.run / 'CAMPAIGN_PROVIDER_BASELINE.json'
            if baseline_path.exists():
                baseline = read(baseline_path)
                if baseline['campaign_auth_sha256'] != sha(self.auth_path):
                    raise RuntimeError('Campaign baseline belongs to different root authorization')
            else:
                if health['counters']['chat_requests_reserved'] != 0:
                    raise RuntimeError('First campaign controller requires zero prior chat reservations')
                baseline = {'campaign_auth_sha256': sha(self.auth_path), 'counter': health['counters'],
                            'log_count': len(meter.rows(self.provider.state / 'requests.jsonl'))}
                write_new(baseline_path, baseline)
            self.provider.initial_counter = baseline['counter']
            self.provider.initial_log_count = baseline['log_count']
            for key, value in baseline['counter'].items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and health['counters'].get(key, value) < value:
                    raise RuntimeError('Provider counter decreased since campaign baseline')
            clock = self.run / 'REFERENCE_CLOCK.json'
            if not clock.exists():
                write_new(clock, {'started_monotonic': time.monotonic(), 'started_at_utc': datetime.now(timezone.utc).isoformat(),
                                  'phase': 'EXTERNAL_V8', 'filename_is_legacy_meter_transport_name': True})
            stage_copy = self.run / 'stages' / (self.stage['stage_id'] + '.json')
            if stage_copy.exists():
                if read(stage_copy) != self.stage:
                    raise RuntimeError('Stage allowance cannot be changed after use')
            else:
                write_new(stage_copy, self.stage)
            self._ledger()
        except BaseException:
            self.close(); raise

    def _ledger(self):
        path = self.run / 'native_reservations.jsonl'
        previous = '0' * 64; entries = []; ids = set()
        if path.exists():
            data = path.read_bytes()
            if data and not data.endswith(b'\n'):
                raise RuntimeError('Torn native reservation ledger')
            for line in data.splitlines():
                row = json.loads(line)
                body = {k: v for k, v in row.items() if k != 'sha256'}
                if row['sha256'] != hashlib.sha256(canonical(body)).hexdigest() or row['previous_sha256'] != previous:
                    raise RuntimeError('Native reservation chain changed')
                if row['index'] != len(entries) + 1 or row['request_id'] in ids:
                    raise RuntimeError('Duplicate or reordered native reservation')
                if row['campaign_auth_sha256'] != sha(self.auth_path):
                    raise RuntimeError('Native reservation belongs to another campaign')
                previous = row['sha256']; entries.append(row); ids.add(row['request_id'])
        head_path = self.run / 'NATIVE_HEAD.json'
        if head_path.exists():
            head = read(head_path)
            if head != {'index': len(entries), 'sha256': previous}:
                raise RuntimeError('Native reservation ledger/head mismatch; do not reset')
        elif entries:
            raise RuntimeError('Native reservation checkpoint missing')
        return entries, ids, previous

    def _reserve(self, request_id, metadata):
        if self.closed or read(self.owner_path) != self.owner:
            raise RuntimeError('Exclusive root dispatch ownership lost')
        if sha(self.auth_path) != self.stage['campaign_auth_sha256'] or read(self.stage_path) != self.stage:
            raise RuntimeError('Live root allowance changed')
        if time.time() >= self.stage['expires_at_epoch']:
            raise RuntimeError('Stage expired')
        if metadata.get('state') not in self.stage['allowed_states'] or metadata.get('task') not in self.stage['allowed_tasks']:
            raise RuntimeError('Unregistered state/task')
        if metadata.get('phase') not in self.stage['allowed_metadata_phases']:
            raise RuntimeError('Query role outside current stage')
        entries, ids, previous = self._ledger()
        stage_count = sum(x['stage_id'] == self.stage['stage_id'] for x in entries)
        if request_id in ids:
            raise RuntimeError('A native query cannot be retried or reserved twice')
        if stage_count >= self.stage['native_query_cap'] or len(entries) >= self.auth['native_query_cap']:
            raise RuntimeError('Native stage/campaign query cap reached')
        if self.auth['prior_native_query_units'] + len(entries) >= self.auth['shared_native_query_cap']:
            raise RuntimeError('Cumulative native query cap reached')
        self.provider.budget()
        row = {'index': len(entries) + 1, 'request_id': request_id, 'stage_id': self.stage['stage_id'],
               'metadata': metadata, 'campaign_auth_sha256': sha(self.auth_path),
               'previous_sha256': previous, 'reserved_at_utc': datetime.now(timezone.utc).isoformat(),
               'global_native_query_units_after': self.auth['prior_native_query_units'] + len(entries) + 1}
        row['sha256'] = hashlib.sha256(canonical(row)).hexdigest()
        append(self.run / 'native_reservations.jsonl', row)
        meter.atomic(self.run / 'NATIVE_HEAD.json', {'index': row['index'], 'sha256': row['sha256']})
        return row

    def _perform(self, request_id, operation, *, chat, reservation=None):
        if self.closed or read(self.owner_path) != self.owner:
            raise RuntimeError('Campaign does not own dispatch')
        if time.time() >= min(self.auth['expires_at_epoch'], self.stage['expires_at_epoch']):
            raise RuntimeError('Stage expired before allocation')
        if read(self.stage_path) != self.stage or sha(self.auth_path) != self.stage['campaign_auth_sha256']:
            raise RuntimeError('Root stage/campaign authorization changed')
        value, receipt = self.provider.perform(request_id, operation, chat=chat)
        receipt['native_query_units_reserved'] = 1 if reservation else 0
        receipt['native_reservation'] = reservation
        if receipt.get('adapter_exception'):
            receipt['dispatch_safe_to_continue'] = False
            if not (self.run / 'ACCOUNTING_BLOCK.json').exists():
                write_new(self.run / 'ACCOUNTING_BLOCK.json', receipt)
        ident = hashlib.sha256(request_id.encode()).hexdigest()[:24]
        receipt_path = self.run / 'sealed' / ('operation_' + ident + '.json')
        receipt['receipt_path'] = str(receipt_path)
        write_new(receipt_path, receipt)
        append(self.run / 'operation_index.jsonl', {'allocation_id': request_id, 'path': str(receipt_path), 'sha256': sha(receipt_path)})
        return value, receipt

    def query(self, request_id, metadata, operation):
        reservation = self._reserve(request_id, metadata)
        return self._perform(request_id, operation, chat=True, reservation=reservation)

    def perform_setup(self, request_id, operation):
        return self._perform(request_id, operation, chat=False)

    def health(self):
        return self.provider.health()

    def close(self):
        if getattr(self, 'closed', True):
            return
        self.closed = True
        if self.owner_path.exists() and read(self.owner_path) == self.owner:
            self.owner_path.unlink()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiment.development_v8.control import Campaign, METER, sha, write_new


class FakeProvider:
    counter = {}

    def health(self):
        return {'counters': copy.deepcopy(self.counter)}

    def budget(self):
        if (self.run / 'ACCOUNTING_BLOCK.json').exists():
            raise RuntimeError('accounting blocked')
        return 100, self.health()

    def perform(self, ident, operation, chat=False):
        self.budget()
        try:
            if chat:
                self.counter['chat_requests_reserved'] += 1
            value = operation(100)
            error = None
        except Exception as exc:
            value, error = None, repr(exc)
        return value, {'allocation_id': ident, 'adapter_exception': error,
                       'dispatch_safe_to_continue': True, 'provider_join': {'joined': True}}


def fixture(tmp_path, cap=4, stagecap=4):
    run = tmp_path / 'run'; state = tmp_path / 'provider'; state.mkdir()
    FakeProvider.counter = {'chat_requests_reserved': 0, 'gpu_allocation_seconds_accounted': 4.0}
    auth = {'provider_phase': 'EXTERNAL_V8', 'campaign_run_dir': str(run.resolve()),
            'provider_state_dir': str(state), 'expires_at_epoch': time.time() + 600,
            'control_source_sha256': sha(ROOT / 'experiment/development_v8/control.py'),
            'provider_meter_source_sha256': sha(METER), 'native_query_cap': cap,
            'prior_native_query_units': 2071, 'shared_native_query_cap': 5000,
            'prior_shared_gpu_seconds': 9316.086159400991,
            'prior_cost_record_sha256': sha(ROOT/'experiment/runs/validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json')}
    ap = tmp_path / 'auth.json'; write_new(ap, auth)
    stage = {'phase': 'EXTERNAL_V8', 'stage_id': 'qualification', 'campaign_auth_sha256': sha(ap),
             'authorized': True, 'expires_at_epoch': time.time() + 600,
             'allowed_states': ['HEALTHY'], 'allowed_tasks': ['T01'],
             'allowed_metadata_phases': ['qualification'], 'native_query_cap': stagecap}
    sp = tmp_path / 'stage.json'; write_new(sp, stage)
    return ap, run, sp


META = {'state': 'HEALTHY', 'task': 'T01', 'phase': 'qualification'}


def test_resume_preserves_prior_native_and_provider_baseline(tmp_path):
    args = fixture(tmp_path)
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        campaign.query('one', META, lambda _: {'value': 'x'})
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        assert campaign.provider.initial_counter['chat_requests_reserved'] == 0
        assert campaign.health()['counters']['chat_requests_reserved'] == 1
        campaign.query('two', META, lambda _: {'value': 'y'})
    rows = [json.loads(x) for x in (args[1] / 'native_reservations.jsonl').read_text().splitlines()]
    assert rows[-1]['global_native_query_units_after'] == 2073


def test_duplicate_query_is_not_dispatched(tmp_path):
    args = fixture(tmp_path)
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        campaign.query('one', META, lambda _: 1)
        with pytest.raises(RuntimeError, match='retried'):
            campaign.query('one', META, lambda _: pytest.fail('duplicate dispatched'))
    assert FakeProvider.counter['chat_requests_reserved'] == 1


def test_stage_cap_stops_before_native_work(tmp_path):
    args = fixture(tmp_path, stagecap=1)
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        campaign.query('one', META, lambda _: 1)
        with pytest.raises(RuntimeError, match='cap'):
            campaign.query('two', META, lambda _: pytest.fail('over-cap dispatched'))


def test_clean_truncation_cannot_reset_counter(tmp_path):
    args = fixture(tmp_path)
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        campaign.query('one', META, lambda _: 1)
    (args[1] / 'native_reservations.jsonl').write_bytes(b'')
    with pytest.raises(RuntimeError, match='head mismatch'):
        Campaign(*args, provider_class=FakeProvider)


def test_unapproved_role_has_no_reservation(tmp_path):
    args = fixture(tmp_path)
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        with pytest.raises(RuntimeError, match='role'):
            campaign.query('one', {**META, 'phase': 'comparison'}, lambda _: 1)
    assert not (args[1] / 'native_reservations.jsonl').exists()


def test_adapter_failure_keeps_reservation_and_blocks_followup(tmp_path):
    args = fixture(tmp_path)
    with Campaign(*args, provider_class=FakeProvider) as campaign:
        def fail(_):
            raise RuntimeError('native readiness failure')
        _, receipt = campaign.query('one', META, fail)
        assert receipt['native_query_units_reserved'] == 1
        assert receipt['dispatch_safe_to_continue'] is False
        with pytest.raises(RuntimeError, match='blocked'):
            campaign.query('two', META, lambda _: 1)


def test_exclusive_dispatch_owner(tmp_path):
    args = fixture(tmp_path)
    with Campaign(*args, provider_class=FakeProvider):
        with pytest.raises(FileExistsError):
            Campaign(*args, provider_class=FakeProvider)

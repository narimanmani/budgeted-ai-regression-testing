"""Prospectively bounded native acquisition; no policy scoring or retuning.

Run only after registration.py has sealed the complete code/data closure. The
bank and fourth-pass confirmations are actual new native invocations. Replay
trajectories are produced separately and must never be counted as native runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

from experiment.transfer_v9.common import ROOT, HERE, PRIOR, read, save, sha, digest, utc, verify_freeze
from experiment.transfer_v9.runtime.ledger import Ledger, zeros
from experiment.transfer_v9.runtime.local_model import launch_backend, MeteredClient, close_backend
from experiment.transfer_v9.runtime.vanna_native import NativeVanna, reference_check as vanna_check
from experiment.transfer_v9.runtime.rasa_native import docker_command

IMAGE = 'rasa/rasa@sha256:a48a3523e70997282c4ab8fd86bd4702f29178a840bcfd6b673b21704f731652'
RASA_SOURCE_SHA = 'a05b457afdb74e86aa1fe8426866817915c5f43d0a0be03db593c20ca2c86f30'
CASES = {'vanna': ('VANNA_SQL_WITHIN', 'VANNA_ASK_FIGURE'),
         'rasa': ('RASA_FORM_TRIGGER', 'RASA_INTENT_RANKING')}
CHANGES = {'vanna': {'A': ['code:src/vanna/base/base.py/extract_sql'],
                     'B': ['code:src/vanna/base/base.py/ask']},
           'rasa': {'A': ['code:rasa/core/actions/forms.py', 'code:rasa/core/actions/loops.py'],
                    'B': ['code:rasa/nlu/classifiers/logistic_regression_classifier.py']}}


def rasa_check(task, observed):
    output, contract = observed['output'], task['contract']
    if task['kind'] == 'form':
        clauses = {key: key in output and output[key] == contract[key] for key in ('slot_value', 'requested_slot', 'active_loop')}
    else:
        ranking = output.get('intent_ranking', [])
        confidences = [item.get('confidence') for item in ranking]
        clauses = {
            'ranking_length': len(ranking) == contract['ranking_length'],
            'first_equals_intent': bool(ranking) and ranking[0] == output.get('intent'),
            'sorted_confidences': all(confidences[i] >= confidences[i+1] for i in range(len(confidences)-1)),
            'valid_names': all(item.get('name') in contract['valid_names'] for item in ranking),
            'confidence_interval': all(isinstance(c, (int, float)) and 0 <= c <= 1 for c in confidences),
        }
    return {'reference_pass': all(clauses.values()), 'clauses': clauses}


class RasaWorker:
    def __init__(self, run, cohort, state, ledger):
        self.run, self.cohort, self.state, self.ledger = Path(run), cohort, state, ledger
        self.directory = self.run / cohort / 'rasa-workers' / state
        self.directory.mkdir(parents=True, exist_ok=False)
        work = self.directory / 'work'
        work.mkdir()
        self.name = 'tosem-v9-rasa-' + self.run.name.lower().replace('_', '-') + '-' + cohort + '-' + state.lower()
        form_state, ranking_state = {'H': ('fixed', 'fixed'), 'A': ('parent', 'fixed'), 'B': ('fixed', 'parent')}[state]
        self.command = docker_command(image=IMAGE, workspace=ROOT, work_dir=work,
            source_root=HERE/'upstream/rasa-f3b733a0c1f1ba9a9b20cac806648dbff2c5d467',
            inventory_path=HERE/'screening/CASE_INVENTORY.json',
            catalog_path=HERE/f'cohorts/{cohort}/rasa.public.json',
            form_state=form_state, ranking_state=ranking_state,
            expected_source_closure_sha256=RASA_SOURCE_SHA, container_name=self.name)
        self.operation = f'{cohort}-rasa-startup-{state}'
        self.process = None
        self.ledger.reserve(self.operation, 'setup', {**zeros(), 'end_to_end_seconds': 300},
                            {'container_name': self.name, 'command': self.command})
        self.started = time.perf_counter()
        self.lines = queue.Queue()
        self.stderr = (self.directory/'stderr.log').open('x', encoding='utf-8')
        try:
            self.process = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, text=True, encoding='utf-8', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
            def reader():
                for line in self.process.stdout:
                    self.lines.put(line)
                self.lines.put(None)
            self.thread = threading.Thread(target=reader, daemon=True)
            self.thread.start()
            self.ready = self.receive(timeout=240)
            save(self.directory/'SETUP.json', {'command': self.command, 'receipt': self.ready,
                 'outer_setup_seconds': time.perf_counter()-self.started})
            if self.ready.get('event') != 'ready':
                raise RuntimeError('Native Rasa setup incident; inspect its preserved receipt')
            self.ledger.settle(self.operation, {**zeros(), 'end_to_end_seconds': time.perf_counter()-self.started},
                status='completed', evidence={'setup_sha256': sha(self.directory/'SETUP.json')})
        except BaseException:
            try:
                self.ledger.settle(self.operation, {**zeros(), 'end_to_end_seconds': time.perf_counter()-self.started},
                    status='failed', evidence={'container_name': self.name})
            finally:
                self.close()
            raise

    def receive(self, timeout=60):
        line = self.lines.get(timeout=timeout)
        if line is None:
            raise RuntimeError('Native Rasa service exited before returning its receipt')
        return json.loads(line)

    def query(self, operation, task_id):
        self.process.stdin.write(json.dumps({'operation_id': operation, 'task_id': task_id})+'\n')
        self.process.stdin.flush()
        result = self.receive(timeout=60)
        if result.get('event') != 'query' or result.get('operation_id') != operation:
            save(self.directory/f'{operation}-INCIDENT.json', result)
            raise RuntimeError('Native Rasa query incident; do not label it a demonstrated product regression')
        return result

    def close(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write('{"command":"close"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                # Exact registered name only; no Docker-wide stop/prune operation.
                subprocess.run(['docker', 'stop', '--time', '5', self.name], capture_output=True, timeout=20)
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
        self.stderr.close()
        if not (self.directory/'CLOSED.json').exists():
            save(self.directory/'CLOSED.json', {'at_utc': utc(), 'container_name': self.name,
                 'process_returncode': None if self.process is None else self.process.poll(),
                 'unrelated_containers_stopped': False})


def state_digest(setting, state, cohort):
    inventory = read(HERE/'screening/CASE_INVENTORY.json')
    methods = []
    for i, case_id in enumerate(CASES[setting]):
        selected = 'parent' if state == ('A' if i == 0 else 'B') else 'fixed'
        case = next(c for c in inventory['case_candidates'] if c['case_id'] == case_id)
        methods.extend((row['path'], row['sha256']) for row in case['bindings'] if row['state'] == selected and row['path'].endswith('.py') and not row['path'].startswith('tests/'))
    public_path = HERE/f'cohorts/{cohort}/rasa.public.json' if setting == 'rasa' else HERE/f'cohorts/{cohort}/vanna.datasource.json'
    return digest({'setting': setting, 'production_bindings': methods,
                   'public_catalog_sha256': sha(public_path),
                   'runtime_adapter_sha256': sha(HERE/f'runtime/{setting}_native.py'),
                   'model_runtime': IMAGE if setting == 'rasa' else 'Qwen2.5-7B-Q4/4096ctx/256out/temp0/cacheoff'})


def acquire(run, ledger, cohort, setting, frame, client=None, worker_pool=None):
    catalog = read(HERE/f'cohorts/{cohort}/{setting}.private.json')
    tasks = {t['task_id']: t for t in catalog['tasks']}
    records = []
    worker, workers = None, {} if worker_pool is None else worker_pool
    try:
        for item in frame:
            ident = item['operation_id']
            task = tasks[item['task_id']]
            state = item['state']
            path = Path(run)/cohort/'raw'/f'{ident}.json'
            if path.exists():
                raise RuntimeError('Never reuse an existing native output identity')
            # CPU worker setup is outside query measurement and explicitly paid.
            if setting == 'rasa':
                if state not in workers:
                    workers[state] = RasaWorker(run, cohort, state, ledger)
                worker = workers[state]
            resource_key = 'native_query_units' if setting == 'vanna' else 'queryfree_native_check_units'
            role = ('profile' if item['frame_role'] == 'live_profile' else
                    'comparison' if item['frame_role'] == 'live_selected' else
                    'qualification' if cohort == 'development' else 'reference')
            ledger.reserve(ident, role, {**zeros(), resource_key: 1, 'end_to_end_seconds': 420},
                {'cohort': cohort, 'setting': setting, 'task_id': task['task_id'], 'state': state,
                 'case_id': item.get('case_id'), 'pass_index': item.get('pass_index'), 'frame_role': item['frame_role'],
                 **({'predecision_sha256': item['predecision_sha256']} if 'predecision_sha256' in item else {})})
            started = time.perf_counter()
            try:
                if setting == 'vanna':
                    public = read(HERE/f'cohorts/{cohort}/vanna.datasource.json')
                    client.role = role
                    client.begin(ident)
                    native = NativeVanna({key: public[key] for key in ('schema', 'rows')}, client,
                        state={'H': 'HEALTHY', 'A': 'A_BAD', 'B': 'B_BAD'}[state],
                        work_dir=Path(run)/cohort/'sqlite'/ident)
                    output = native.query({key: task[key] for key in ('task_id', 'family', 'question')})
                    chats = client.end()
                    if client.pending_failure:
                        raise RuntimeError('A provider/accounting incident blocks all further native work')
                    check_start = time.perf_counter()
                    verdict = vanna_check(task, output)
                    checker_seconds = time.perf_counter()-check_start
                    feature_start = time.perf_counter()
                    dependencies = output['trace_tokens']
                    feature_seconds = time.perf_counter()-feature_start
                else:
                    output = worker.query(ident, task['task_id'])
                    chats = []
                    check_start = time.perf_counter()
                    verdict = rasa_check(task, output)
                    checker_seconds = time.perf_counter()-check_start
                    feature_start = time.perf_counter()
                    dependencies = ['code:'+p for p in output['trace']['production_paths']]
                    feature_seconds = time.perf_counter()-feature_start
                elapsed = time.perf_counter()-started
                receipt = {'schema': 'v9-native-observation-1', 'operation_id': ident, 'at_utc': utc(),
                    'frame': item, 'setting_id': setting, 'cohort': cohort,
                    'native_output': output, 'reference': verdict, 'provider_call_ids': chats,
                    'checker_seconds': checker_seconds, 'feature_seconds': feature_seconds,
                    'outer_query_seconds_excluding_checker_feature': max(1e-9, elapsed-checker_seconds-feature_seconds),
                    'reference_not_supplied_to_application_or_selector': True,
                    'state_digest': state_digest(setting, state, cohort)}
                save(path, receipt)
                ledger.settle(ident, {**zeros(), resource_key: 1, 'end_to_end_seconds': elapsed},
                    status='completed', evidence={'raw_sha256': sha(path), 'provider_call_ids': chats})
                normalized = {'record_id': ident, 'setting_id': setting, 'case_id': item.get('case_id'),
                    'state': state, 'task_id': task['task_id'], 'pass_index': item.get('pass_index', 0),
                    'contract_pass': verdict['reference_pass'],
                    'elapsed_seconds': receipt['outer_query_seconds_excluding_checker_feature'],
                    'checker_seconds': checker_seconds, 'feature_seconds': feature_seconds,
                    'observed_dependency_tokens': dependencies, 'raw_sha256': sha(path),
                    'receipt_sha256': sha(path), 'raw_path': path.relative_to(ROOT).as_posix(),
                    'frame_role': item['frame_role']}
                records.append(normalized)
                print(json.dumps({'stage': cohort, 'setting': setting, 'operation': ident,
                                  'completed': len(records), 'reference_pass': verdict['reference_pass']}), flush=True)
            except BaseException as exc:
                if not path.exists():
                    save(path, {'operation_id': ident, 'frame': item, 'status': 'study_incident',
                                'exception_type': type(exc).__name__, 'message': str(exc)})
                try:
                    ledger.settle(ident, {**zeros(), resource_key: 1,
                        'end_to_end_seconds': time.perf_counter()-started}, status='failed',
                        evidence={'incident_sha256': sha(path)})
                except BaseException:
                    pass
                raise
    finally:
        if worker_pool is None:
            for worker in workers.values():
                worker.close()
    return records


def development_gate(records, frame):
    by_id = {r['record_id']: r for r in records}
    checks = []
    for row in frame:
        expected = row['required_contract_pass']
        checks.append({'operation_id': row['operation_id'], 'expected': expected,
                       'observed': by_id[row['operation_id']]['contract_pass'],
                       'passed': by_id[row['operation_id']]['contract_pass'] == expected})
    return {'passed': all(row['passed'] for row in checks), 'conditions': checks,
            'criteria_changed_after_outputs': False, 'replacement_or_prompt_search_allowed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--mode', choices=['development', 'validation'], required=True)
    args = parser.parse_args(argv)
    run = args.run.resolve()
    protocol = verify_freeze(run/'STUDY_FREEZE.json')
    plan = read(HERE/'cohorts/FRAME.json')
    if args.mode == 'validation' and not read(run/'DEVELOPMENT_GATE.json')['passed']:
        raise RuntimeError('Fresh validation is closed after an unsuccessful fixed development configuration')
    records = []
    backend = None
    with Ledger(run/'accounting', run/'RESOURCE_MANIFEST.json', PRIOR) as ledger:
        try:
            # The CPU application and GPU model are never resident together.
            directory = run/args.mode/'backend'
            backend = launch_backend(directory, ledger, operation_id=args.mode+'-model-startup')
            client = MeteredClient(ledger, run/args.mode/'provider',
                                   role='qualification' if args.mode == 'development' else 'reference')
            rows = plan[args.mode]['vanna']
            records += acquire(run, ledger, args.mode, 'vanna', rows, client)
            live = []
            if args.mode == 'validation':
                from experiment.transfer_v9.live_confirmation import run_setting
                live += run_setting(run, ledger, 'vanna', client=client)
            close_backend(backend, directory)
            backend = None
            workers = {}
            try:
                records += acquire(run, ledger, args.mode, 'rasa', plan[args.mode]['rasa'], worker_pool=workers)
                if args.mode == 'validation':
                    live += run_setting(run, ledger, 'rasa', worker_pool=workers)
            finally:
                for worker in workers.values():
                    worker.close()
            if args.mode == 'development':
                all_frame = plan['development']['vanna']+plan['development']['rasa']
                save(run/'DEVELOPMENT_RECORDS.json', records)
                gate = development_gate(records, all_frame)
                save(run/'DEVELOPMENT_GATE.json', gate)
                print(json.dumps({'development_gate': gate['passed']}), flush=True)
            else:
                settings = []
                for setting in ('vanna', 'rasa'):
                    catalog = read(HERE/f'cohorts/validation/{setting}.private.json')
                    if setting == 'vanna':
                        setup_seconds = read(run/'validation/backend/READY.json')['startup_generation_allocation_seconds']
                    else:
                        setup_seconds = sum(read(p)['outer_setup_seconds'] for p in
                                            sorted((run/'validation/rasa-workers').glob('*/SETUP.json')))
                    settings.append({'setting_id': setting, 'task_ids': [t['task_id'] for t in catalog['tasks']],
                        'common_setup_seconds': setup_seconds,
                        'states': {s: {'state_digest': state_digest(setting, s, 'validation'),
                                      'changed_tokens': [] if s == 'H' else CHANGES[setting][s]} for s in ('H', 'A', 'B')},
                        'case_ids': dict(zip(('A', 'B'), CASES[setting]))})
                bank = {'schema_version': 'v9-native-bank-1', 'settings': settings,
                        'records': [r for r in records if r['frame_role'] == 'primary_bank'],
                        'study_freeze_sha256': sha(run/'STUDY_FREEZE.json'),
                        'not_live_policy_execution': True}
                save(run/'NATIVE_BANK.json', bank)
                save(run/'FRESH_CONFIRMATION.json', {**bank,
                    'records': [r for r in records if r['frame_role'] == 'fresh_confirmation']})
                save(run/'LIVE_POLICY_CONFIRMATION.json', {'schema': 'v9-live-policy-confirmation-1',
                    'cells': live, 'cells_planned': 4, 'case_scope': 'first A change only, initially empty history',
                    'matched_native_request_ceiling_per_cell': 28,
                    'extra_independent_upstream_cases': 0, 'long_history_or_noisy_checker_live_claimed': False,
                    'registration_plan_sha256': sha(HERE/'cohorts/LIVE_CONFIRMATION_PLAN.json'),
                    'study_freeze_sha256': sha(run/'STUDY_FREEZE.json')})
            save(run/(args.mode.upper()+'_RESOURCE_SUMMARY.json'), ledger.summary())
        except BaseException as exc:
            preserved = sum(read(p).get('schema') == 'v9-native-observation-1'
                            for p in (run/args.mode/'raw').glob('*.json'))
            save(run/(args.mode.upper()+'_STOP.json'), {'at_utc': utc(), 'type': type(exc).__name__,
                'message': str(exc), 'complete_native_observation_receipts_preserved_before_stop': preserved,
                'no_replacement_or_retuning': True, 'resource_summary': ledger.summary()})
            raise
        finally:
            if backend is not None:
                close_backend(backend, run/args.mode/'backend')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

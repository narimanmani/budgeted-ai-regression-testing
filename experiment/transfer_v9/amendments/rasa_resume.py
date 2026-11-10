"""Resume only unexecuted Rasa development after a dependency import incident.

Vanna's 16 completed observations are retained, never reacquired. The original
ledger, caps, guide, inputs, contracts and native core source remain unchanged.
The added locked dependency is exposed on a read-only path in the same image.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiment.transfer_v9.common import ROOT, HERE, PRIOR, read, save, sha, digest, utc, freeze, verify_freeze
from experiment.transfer_v9 import collect as core
from experiment.transfer_v9.runtime.ledger import Ledger
from experiment.transfer_v9.amendments import rasa_dependency

DEPENDENCY = HERE/'amendments/rasa_env/DEPENDENCY_RECEIPT.json'


class SetupNamespace:
    def __init__(self, ledger, prefix):
        self.ledger, self.prefix = ledger, prefix
    def reserve(self, ident, *args, **kwargs):
        return self.ledger.reserve(self.prefix+ident, *args, **kwargs)
    def settle(self, ident, *args, **kwargs):
        return self.ledger.settle(self.prefix+ident, *args, **kwargs)
    def __getattr__(self, key):
        return getattr(self.ledger, key)


def configure_core(namespace):
    """Explicit environment shim; no edits to frozen source or scientific inputs."""
    core.docker_command = rasa_dependency.command_shim(core.docker_command)
    original_worker, original_digest = core.RasaWorker, core.state_digest
    def worker(run, cohort, state, ledger):
        return original_worker(run, cohort, state, SetupNamespace(ledger, namespace))
    def state_digest(setting, state, cohort):
        original = original_digest(setting, state, cohort)
        if setting != 'rasa':
            return original
        return digest({'frozen_core_state_digest': original,
                       'locked_missing_dependency_receipt_sha256': sha(DEPENDENCY)})
    core.RasaWorker, core.state_digest = worker, state_digest


def recovered_vanna(run):
    """Normalize already completed receipts; no application or model executes."""
    result = []
    for row in read(run/'ENGINEERING_RETRY_FRAME.json')['vanna']:
        path = run/'engineering_retry2/development/raw'/f"{row['operation_id']}.json"
        raw = read(path)
        if raw.get('schema') != 'v9-native-observation-1' or raw['frame'] != row:
            raise RuntimeError('Completed Vanna receipt is missing or its immutable frame changed')
        result.append({'record_id': row['operation_id'], 'setting_id': 'vanna', 'case_id': row['case_id'],
            'state': row['state'], 'task_id': row['task_id'], 'pass_index': row['pass_index'],
            'contract_pass': raw['reference']['reference_pass'],
            'elapsed_seconds': raw['outer_query_seconds_excluding_checker_feature'],
            'checker_seconds': raw['checker_seconds'], 'feature_seconds': raw['feature_seconds'],
            'observed_dependency_tokens': raw['native_output']['trace_tokens'],
            'raw_sha256': sha(path), 'receipt_sha256': sha(path),
            'raw_path': path.relative_to(ROOT).as_posix(), 'frame_role': row['frame_role']})
    return result


def declare(run):
    run = Path(run).resolve()
    verify_freeze(run/'STUDY_FREEZE.json')
    verify_freeze(run/'ENGINEERING_AMENDMENT_FREEZE.json')
    if not DEPENDENCY.is_file():
        raise RuntimeError('Locked dependency installation and complete import preflight must finish first')
    source_stop = run/'engineering_retry2/development/rasa-workers/H/SETUP.json'
    if read(source_stop)['receipt']['message'] != "No module named 'telebot'":
        raise RuntimeError('Unexpected incident; this amendment is limited to the missing locked dependency')
    original_frame = read(HERE/'cohorts/FRAME.json')['development']['rasa']
    frame = [{**row, 'operation_id': 'retry3-'+row['operation_id']} for row in original_frame]
    save(run/'RASA_REMAINING_DEVELOPMENT_FRAME.json', frame)
    save(run/'RASA_DEPENDENCY_AMENDMENT.json', {
        'schema': 'v9-prospective-rasa-dependency-amendment-1', 'at_utc': utc(),
        'reason': 'Pinned source requires locked pyTelegramBotAPI4.7.0, absent from the later patch-level dependency image.',
        'original_source_poetry_lock': 'experiment/transfer_v9/upstream/rasa-f3b733a0c1f1ba9a9b20cac806648dbff2c5d467/poetry.lock',
        'dependency_receipt_sha256': sha(DEPENDENCY),
        'original_study_freeze_sha256': sha(run/'STUDY_FREEZE.json'),
        'first_amendment_freeze_sha256': sha(run/'ENGINEERING_AMENDMENT_FREEZE.json'),
        'stopped_setup_sha256': sha(source_stop),
        'remaining_frame_sha256': sha(run/'RASA_REMAINING_DEVELOPMENT_FRAME.json'),
        'completed_development_roots': {'vanna': 'engineering_retry2/development', 'rasa': 'engineering_rasa3/development'},
        'completed_development_operation_prefixes': {'vanna': 'retry2-', 'rasa': 'retry3-'},
        'rasa_model_answers_or_task_queries_seen_before_amendment': 0,
        'completed_vanna_observations_reused_without_rerun': 16,
        'original_core_source_bytes_edited': False,
        'questions_contracts_prompt_or_guide_changed': False,
        'docker_base_image_changed': False,
        'dependency_path_mount': 'read-only, pure Python package on explicit PYTHONPATH',
        'same_original_phase_ledger_and_caps': True, 'counter_reset': False,
        'added_failed_query_attempts_so_far': 1,
        'complete_native_case_attempt_plan_including_failure': 377,
        'cap_unchanged': 400,
        'new_policy_or_case_selection_based_on_outcomes': False})
    files = [Path(__file__), HERE/'amendments/rasa_dependency.py', DEPENDENCY,
             run/'RASA_REMAINING_DEVELOPMENT_FRAME.json', run/'RASA_DEPENDENCY_AMENDMENT.json',
             run/'STUDY_FREEZE.json', run/'ENGINEERING_AMENDMENT_FREEZE.json']
    files += [p for p in (HERE/'amendments/rasa_env').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    freeze(files, run/'RASA_DEPENDENCY_AMENDMENT_FREEZE.json',
           role='Missing locked dependency, before first Rasa task and before all fresh validation',
           metadata={'actual_rasa_task_queries_before_freeze': 0, 'original_vanna_data_not_reacquired': True})


def execute(run):
    run = Path(run).resolve()
    for name in ('STUDY_FREEZE.json', 'ENGINEERING_AMENDMENT_FREEZE.json', 'RASA_DEPENDENCY_AMENDMENT_FREEZE.json'):
        verify_freeze(run/name)
    if (run/'DEVELOPMENT_GATE.json').exists():
        raise RuntimeError('Development qualification has already closed')
    records = recovered_vanna(run)
    frame = read(run/'RASA_REMAINING_DEVELOPMENT_FRAME.json')
    child = run/'engineering_rasa3'
    child.mkdir(exist_ok=False)
    configure_core('rasa3-')
    workers = {}
    with Ledger(run/'accounting', run/'RESOURCE_MANIFEST.json', PRIOR) as ledger:
        try:
            records += core.acquire(child, ledger, 'development', 'rasa', frame, worker_pool=workers)
            for worker in workers.values():
                worker.close()
            workers.clear()
            save(run/'DEVELOPMENT_RECORDS.json', records)
            all_frame = read(run/'ENGINEERING_RETRY_FRAME.json')['vanna']+frame
            gate = core.development_gate(records, all_frame)
            gate.update(original_first_launch_failed=True, original_first_launch_reported_successful=False,
                failed_attempt_retained=True, engineering_incidents_retained=2,
                engineering_amendment_sha256=sha(run/'ENGINEERING_AMENDMENT.json'),
                rasa_dependency_amendment_sha256=sha(run/'RASA_DEPENDENCY_AMENDMENT.json'),
                completed_stage_roots=read(run/'RASA_DEPENDENCY_AMENDMENT.json')['completed_development_roots'])
            save(run/'DEVELOPMENT_GATE.json', gate)
            save(run/'DEVELOPMENT_RESOURCE_SUMMARY.json', ledger.summary())
            print({'development_gate_passed': gate['passed'], 'total_completed_native_observations': len(records)}, flush=True)
        except BaseException as exc:
            save(child/'STOP.json', {'at_utc': utc(), 'type': type(exc).__name__, 'message': str(exc),
                                   'resource_summary': ledger.summary(), 'no_scientific_rule_changes': True})
            raise
        finally:
            for worker in workers.values():
                worker.close()


def validation(run):
    run = Path(run).resolve()
    verify_freeze(run/'RASA_DEPENDENCY_AMENDMENT_FREEZE.json')
    configure_core('rasa3-')
    return core.main(['--run', str(run), '--mode', 'validation'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--mode', choices=('declare', 'development', 'validation'), required=True)
    args = parser.parse_args()
    return {'declare': declare, 'development': execute, 'validation': validation}[args.mode](args.run)


if __name__ == '__main__':
    main()

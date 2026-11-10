"""Prospective missing-dependency engineering amendment; frozen core reused.

The original failed startup and its charges remain in the SAME phase ledger.
No model answer existed at the failure. No source, question, reference, prompt,
generation parameter, guidance rule, scientific gate or numerical cap changes.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

from experiment.transfer_v9.common import HERE, ROOT, PRIOR, read, save, sha, freeze, verify_freeze, utc
from experiment.transfer_v9.collect import acquire, development_gate
from experiment.transfer_v9.runtime.ledger import Ledger
from experiment.transfer_v9.runtime.local_model import launch_backend, close_backend, MeteredClient


def declare(run):
    run = Path(run).resolve()
    verify_freeze(run/'STUDY_FREEZE.json')
    if list((run/'development/provider').glob('*-request.json')):
        raise RuntimeError('This amendment is limited to the documented pre-provider missing-dependency failure')
    if read(run/'DEVELOPMENT_STOP.json')['type'] != 'ModuleNotFoundError':
        raise RuntimeError('Different failure requires its own explicit prospective engineering declaration')
    if not read(run/'development/backend/CLOSED.json')['only_owned_popen_handle_closed']:
        raise RuntimeError('Original model launch must be closed first')
    versions = {name: importlib.metadata.version(name) for name in
                ('requests', 'urllib3', 'charset-normalizer', 'certifi', 'idna',
                 'pandas', 'numpy', 'plotly', 'sqlparse', 'openai')}
    save(run/'ENGINEERING_ENVIRONMENT_ADDITION.json', {'at_utc': utc(), 'packages': versions,
        'missing_required_dependency': 'requests==2.32.3',
        'transitive_dependency_added': 'urllib3==2.8.0',
        'source_basis': 'requests is a declared upstream Vanna core dependency',
        'pure_import_preflight': 'Pinned vanna.base.base and vanna.openai.openai_chat import successfully',
        'synthetic_plot_dependency_preflight': 'Two unrelated two-point bar/scatter figures constructed successfully',
        'application_instances_or_model_calls_in_preflight': 0})
    amended_frame = {sid: [{**row, 'operation_id': 'retry2-'+row['operation_id']}
                          for row in read(HERE/'cohorts/FRAME.json')['development'][sid]]
                     for sid in ('vanna', 'rasa')}
    save(run/'ENGINEERING_RETRY_FRAME.json', amended_frame)
    save(run/'ENGINEERING_AMENDMENT.json', {
        'schema': 'v9-prospective-engineering-amendment-1', 'at_utc': utc(),
        'reason': 'The first development native initialization could not import the upstream-required requests package.',
        'prior_study_freeze_sha256': sha(run/'STUDY_FREEZE.json'),
        'original_stop_sha256': sha(run/'DEVELOPMENT_STOP.json'),
        'original_stop_audit': 'audits/INDEPENDENT_ORIGINAL_DEVELOPMENT_STOP_V2.json',
        'original_model_provider_boundaries': 0, 'native_or_model_answers_seen': 0,
        'retained_failed_native_attempts': 1,
        'counter_reset': False, 'numerical_cap_increase': False,
        'output_subdirectory': 'engineering_retry2', 'operation_id_prefix': 'retry2-',
        'retry_frame_sha256': sha(run/'ENGINEERING_RETRY_FRAME.json'),
        'environment_addition_sha256': sha(run/'ENGINEERING_ENVIRONMENT_ADDITION.json'),
        'new_orchestrator_sha256': sha(__file__),
        'original_core_source_or_data_bytes_changed': False,
        'prompt_checker_guidance_model_or_generation_settings_changed': False,
        'qualification_criteria_changed': False, 'extra_native_observations_added_to_plan': 0,
        'complete_new_phase_attempt_ceiling_after_retained_failure': 377,
        'native_case_operation_cap_unchanged': 400,
        'new_first_launch_success_claimed': False})
    freeze([Path(__file__), run/'ENGINEERING_ENVIRONMENT_ADDITION.json', run/'ENGINEERING_RETRY_FRAME.json',
            run/'ENGINEERING_AMENDMENT.json', run/'STUDY_FREEZE.json'],
           run/'ENGINEERING_AMENDMENT_FREEZE.json', role='Dependency-only retry before any application/model answer',
           metadata={'new_scientific_conditions': 0, 'original_failed_attempt_retained': True})


def execute(run):
    run = Path(run).resolve()
    verify_freeze(run/'STUDY_FREEZE.json')
    verify_freeze(run/'ENGINEERING_AMENDMENT_FREEZE.json')
    if (run/'DEVELOPMENT_GATE.json').exists():
        raise RuntimeError('No repeated qualification after a completed gate')
    child = run/'engineering_retry2'
    child.mkdir(exist_ok=False)
    frame = read(run/'ENGINEERING_RETRY_FRAME.json')
    records, workers, backend = [], {}, None
    with Ledger(run/'accounting', run/'RESOURCE_MANIFEST.json', PRIOR) as ledger:
        try:
            backend = launch_backend(child/'development/backend', ledger,
                                     operation_id='dependency-retry2-model-startup')
            client = MeteredClient(ledger, child/'development/provider', role='qualification')
            records += acquire(child, ledger, 'development', 'vanna', frame['vanna'], client)
            close_backend(backend, child/'development/backend')
            backend = None
            records += acquire(child, ledger, 'development', 'rasa', frame['rasa'], worker_pool=workers)
            for worker in workers.values():
                worker.close()
            workers.clear()
            save(run/'DEVELOPMENT_RECORDS.json', records)
            gate = development_gate(records, frame['vanna']+frame['rasa'])
            gate.update(engineering_amendment_sha256=sha(run/'ENGINEERING_AMENDMENT.json'),
                        original_first_launch_failed=True, failed_attempt_retained=True,
                        completed_output_subdirectory='engineering_retry2',
                        original_first_launch_reported_successful=False)
            save(run/'DEVELOPMENT_GATE.json', gate)
            save(run/'DEVELOPMENT_RESOURCE_SUMMARY.json', ledger.summary())
            print({'development_gate_passed': gate['passed'], 'completed_native_observations': len(records)}, flush=True)
        except BaseException as exc:
            preserved = sum(read(p).get('schema') == 'v9-native-observation-1'
                            for p in (child/'development/raw').glob('*.json'))
            save(child/'DEVELOPMENT_RETRY_STOP.json', {'at_utc': utc(), 'type': type(exc).__name__,
                'message': str(exc), 'complete_native_observation_receipts_preserved': preserved,
                'resource_summary': ledger.summary(), 'scientific_gate_or_cap_changed': False})
            raise
        finally:
            if backend is not None:
                close_backend(backend, child/'development/backend')
            for worker in workers.values():
                worker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--declare', action='store_true')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.declare:
        declare(args.run)
    elif args.execute:
        execute(args.run)
    else:
        parser.error('Select exactly one of --declare or --execute')


if __name__ == '__main__':
    main()

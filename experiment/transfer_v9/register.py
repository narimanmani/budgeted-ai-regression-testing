"""Seal a new, separate prospective study; never reopen a legacy account."""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
import sys

from experiment.transfer_v9.common import ROOT, HERE, PRIOR, GUIDANCE, verify_foundation, read, save, sha, freeze, utc
from experiment.transfer_v9.runtime.ledger import SCHEMA, zeros
from experiment.transfer_v9.design.validate_design import validate_design, planned_counts


def register(run):
    prior = verify_foundation()
    run = Path(run).resolve()
    run.relative_to(ROOT/'experiment/runs')
    run.mkdir(parents=True, exist_ok=False)
    protocol = read(HERE/'design/protocol.template.json')
    protocol['status'] = 'PROSPECTIVELY_SEALED_BEFORE_ANY_NATIVE_DEVELOPMENT_OR_VALIDATION_OUTPUT'
    protocol['registered_at_utc'] = utc()
    protocol['formal_external_registration'] = False
    protocol['new_phase_resources'].update({
        'declaration_basis': 'Researcher-chosen bounded envelope for the user-requested follow-up study. '
            'The user authorized the research actions, not these numerical values. The completed 5000-unit account is closed and unchanged.',
        'native_component_request_cap': 400,
        'new_llm_generation_request_cap': 600,
        'new_generation_allocation_seconds_cap': 1800,
        'new_provider_meter_separate_from_closed_legacy': True,
        'new_model_runtime_pinned_and_frozen': True,
        'maximum_generative_native_requests': 200,
        'maximum_queryfree_native_requests': 200,
        'native_generation_and_queryfree_counts_reported_separately': True,
        'new_instrumented_end_to_end_seconds_cap': 14400,
    })
    protocol['native_configuration_development'] = {
        'native_requests_per_setting': 16, 'settings': 2, 'total_native_request_plan': 32,
        'frame_path': 'experiment/transfer_v9/cohorts/FRAME.json',
        'one_fixed_configuration': True, 'prompt_or_selector_search': False,
        'complete_healthy_contracts_required': True, 'registered_fault_witnesses_required': True,
        'failure_means_stop_before_fresh_validation': True,
        'runtime_engineering_incidents_retained_and_distinguished_from_product_contract_failures': True,
        'all_validation_case_bytes_committed_before_development_outputs': True,
    }
    protocol['execution_boundary_details'] = {
        'vanna': 'Actual pinned public generate_sql/ask APIs, actual local Qwen generation, SQLite execution and Plotly; '
            'complete-schema retrieval extension and exact historical-method overlays. No full vector-store or browser deployment claim.',
        'rasa': 'Actual pinned full Rasa source with exact historical-module overlays; native forms from parsed entity events '
            'and an actually trained CPU CountVectors/LogisticRegression pipeline. No raw-text end-to-end dialogue-agent claim.',
        'function_evidence_granularity': 'Vanna change functions are derived from upstream method diffs and matched to actual old call traces; '
            'Rasa uses actual production-file traces. Evidence granularity differs from the earlier broad-module workload; CG1 bytes do not change.',
        'interventions': 'Controlled reintroductions of four independent upstream bug fixes in frozen host implementations; '
            'authored finite conformance workloads and constructed repeated fault/repair sequences, not sampled natural industrial maintenance.',
        'full_cost_claim': 'Matched total native-request budgets with charged acquisitions and exact-state reuse. '
            'Instrumented native, checker, feature, setup and decision seconds are descriptive allocations; no matched-wall throughput or energy claim.',
    }
    save(run/'PROTOCOL.json', protocol)
    inventory = read(HERE/'screening/CASE_INVENTORY.json')
    candidates = inventory['case_candidates']
    settings, cases = [], []
    for sid in ('vanna', 'rasa'):
        catalog = HERE/f'cohorts/validation/{sid}.private.json'
        task_ids = [t['task_id'] for t in read(catalog)['tasks']]
        settings.append({'setting_id': sid, 'native_boundary': 'native_component',
            'previously_used_for_guidance_development': False, 'validation_task_ids': task_ids})
        for case in candidates:
            if (case['repo'].lower().startswith('vanna') if sid == 'vanna' else case['repo'].lower().startswith('rasahq')):
                pin = 'vanna-67f1bceda676ef8b5c6acea7c547ce1e5c67b96a' if sid == 'vanna' else 'rasa-f3b733a0c1f1ba9a9b20cac806648dbff2c5d467'
                license_candidates = list((HERE/'upstream'/pin).glob('LICENSE*'))
                if not license_candidates:
                    raise RuntimeError('Missing upstream license')
                cases.append({'case_id': case['case_id'], 'setting_id': sid,
                    'upstream_repository_url': 'https://github.com/'+case['repo'],
                    'upstream_change_url': case['fix_url'], 'buggy_commit': case['parent'],
                    'fixed_commit': case['fix'], 'fix_parent_commit': case['parent'],
                    'mechanism_id': case['case_id'], 'case_origin': 'upstream_historical_bugfix',
                    'intervention_direction': 'controlled_reintroduction', 'native_boundary': 'native_component',
                    'production_path': '; '.join(p for p in case['files'] if not p.startswith('tests/')),
                    'entry_point': case['native_path'], 'upstream_contract_evidence': case['fix_url'],
                    'contract_path': catalog.relative_to(ROOT).as_posix(), 'contract_sha256': sha(catalog),
                    'source_manifest_path': 'experiment/transfer_v9/screening/CASE_INVENTORY.json',
                    'source_manifest_sha256': sha(HERE/'screening/CASE_INVENTORY.json'),
                    'validation_task_ids': task_ids, 'selection_used_policy_scores': False,
                    'license_path': license_candidates[0].relative_to(ROOT).as_posix()})
    paths = [p for p in HERE.rglob('*') if p.is_file() and p.name != 'RUN_HANDOFF.md' and not any(x in p.relative_to(HERE).parts
             for x in ('env', 'audits', '__pycache__', '.pytest_cache', '.git')) and p.suffix.lower() not in ('.pyc', '.pyo')]
    paths += [GUIDANCE, PRIOR, ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json']
    paths += [ROOT/'experiment/runs/development_v8_20261101/backend/ASSET_RECHECK.json',
              ROOT/'experiment/runs/development_v8_20261101/backend/START_RECEIPT.json',
              ROOT/'experiment/native_v3/provider_llamacpp/qwen2_5_7b_official.jinja']
    source_manifest = {'at_utc': utc(), 'purpose': 'Available native sources, complete inputs and execution/replay code before any actual study outputs',
        'files': {p.relative_to(ROOT).as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(paths)}}
    save(run/'SOURCE_MANIFEST.json', source_manifest)
    registry = {'schema_version': 'transfer-v9-registry-1', 'status': 'SOURCE_REGISTERED_BEFORE_OUTPUTS',
        'settings': settings, 'cases': cases, 'freeze': {'sealed_before_native_validation_outputs': True,
            'manifest_sha256': sha(run/'SOURCE_MANIFEST.json'), 'all_required_bytes_available': True,
            'no_validation_policy_scores_seen': True}}
    save(run/'CASE_REGISTRY.json', registry)
    admission = validate_design(protocol, registry, workspace=ROOT, verify_bytes=True)
    save(run/'STRUCTURAL_ADMISSION.json', admission)
    if admission['status'] != 'PASS_STRUCTURAL_ADMISSION':
        raise RuntimeError('Prospective structural admission failed; inspect preserved registration')
    manifest = {'schema': SCHEMA, 'phase_id': run.name,
        'prior_receipt_sha256': sha(PRIOR), 'prior_native_query_units': prior['native_units_cumulative'],
        'prior_generation_allocation_seconds': prior['cumulative_generation_allocation_seconds'],
        'phase_caps': {**zeros(), 'native_query_units': 200, 'queryfree_native_check_units': 200,
                       'provider_chat_units': 600, 'generation_allocation_seconds': 1800,
                       'end_to_end_seconds': 14400},
        'cumulative_caps': {'native_query_units': 5138,
                           'generation_allocation_seconds': prior['cumulative_generation_allocation_seconds']+1800},
        'protocol_sha256': sha(run/'PROTOCOL.json'),
        'cap_basis': protocol['new_phase_resources']['declaration_basis'],
        'old_campaign_envelope_unchanged': True, 'execution_allowed': True}
    save(run/'RESOURCE_MANIFEST.json', manifest)
    versions = {name: importlib.metadata.version(name) for name in
                ('pandas', 'numpy', 'plotly', 'sqlparse', 'openai', 'httpx', 'Flask', 'flask-sock', 'SQLAlchemy')}
    save(run/'PYTHON_ENVIRONMENT.json', {'python': sys.version, 'executable': sys.executable,
        'executable_sha256': sha(sys.executable), 'packages': versions,
        'rasa_dependency_image': 'rasa/rasa@sha256:a48a3523e70997282c4ab8fd86bd4702f29178a840bcfd6b673b21704f731652'})
    freeze(paths + list(run.glob('*.json')), run/'STUDY_FREEZE.json',
        role='prospective native development, fresh validation, factorial replay and fresh fourth-pass observations',
        metadata={'new_native_queries_or_native_cpu_tasks_before_freeze': 0,
                  'validation_answers_or_policy_scores_seen': False, 'planned_counts': planned_counts(protocol),
                  'development_native_request_plan': 32, 'complete_native_plan_ceiling': 376})
    return {'run': str(run), 'freeze_sha256': sha(run/'STUDY_FREEZE.json'),
            'planned_native_observation_ceiling': 376, 'source_registered_upstream_cases': len(cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(register(args.run)), flush=True)


if __name__ == '__main__':
    main()

"""Declare the additional RetestAll diagnostic without dispatching native work.

The primary study is already running. This separate declaration does not amend
its frozen matrix or success criteria, and it precedes the diagnostic's queries.
"""
from pathlib import Path
from experiment.development_v8.control import read, sha, write_new
from experiment.development_v8.execution.preflight import load_case, validate_outer_freeze
from experiment.development_v8.execution.runner import utc

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT/'experiment/runs/development_v8_20261101'
ORDER = (('openwebui', 1), ('dify', 1), ('openwebui', 2), ('dify', 2))


def main():
    registration_path = RUN/'SECONDARY_RETESTALL_REGISTRATION.json'
    if registration_path.exists() or (RUN/'SECONDARY_BASELINE.json').exists():
        raise RuntimeError('The diagnostic declaration/baseline cannot be overwritten or resumed')
    freeze = RUN/'VALIDATION_FREEZE.json'
    outer, mapping = validate_outer_freeze(freeze)
    authority = read(RUN/'CAMPAIGN_AUTH.json')
    source_files = [ROOT/'experiment/development_v8'/name for name in
                    ('secondary_retestall.py', 'test_secondary_retestall.py', 'register_secondary.py')]
    if not all(path.is_file() for path in source_files):
        raise RuntimeError('Completed diagnostic implementation and offline tests required')
    slots = []; configs = []; stages = []
    for app, rep in ORDER:
        case = load_case(freeze, app)
        config_path = RUN/'runtime_configs'/f'secondary_retestall_{app}_r{rep}.json'
        stage_path = RUN/'stage_authorities'/f'secondary_retestall_{app}_r{rep}.json'
        output = RUN/f'secondary-retestall-{app}-r{rep}'
        if any(path.exists() for path in (config_path, stage_path, output)):
            raise RuntimeError('A proposed diagnostic slot has already been used')
        config = read(RUN/'runtime_configs'/f'main_{app}_r{rep}.json')
        config['receipt_scope'] = f'secondary-retestall-{app}-r{rep}'
        if (config['scope_id'] != 'validation-'+case['scope']['prompt_candidate_id']
                or config['allow_new_dataset_scope'] is not False):
            raise RuntimeError('Only the admitted validation dataset scope may be reused')
        configs.append((config_path, config))
        stages.append((stage_path, {'phase': 'EXTERNAL_V8',
            'stage_id': f'secondary_retestall_{app}_r{rep}', 'authorized': True,
            'campaign_auth_sha256': sha(RUN/'CAMPAIGN_AUTH.json'),
            'expires_at_epoch': authority['expires_at_epoch'],
            'allowed_states': ['HEALTHY', 'A_BAD', 'B_BAD'], 'allowed_tasks': case['task_ids'],
            'allowed_metadata_phases': ['secondary_retestall'], 'native_query_cap': 48,
            'validation_freeze_sha256': sha(freeze),
            'input_freeze_sha256': sha(case['input_freeze_path']), 'allowed_scope': case['scope']}))
        slots.append({'app': app, 'repetition': rep, 'output_dir': str(output),
                      'runtime_config_file': str(config_path), 'stage_authority_file': str(stage_path)})
    if not (RUN/'main-openwebui-r1/block/BLOCK_EXECUTION_RESERVATION.json').is_file():
        raise RuntimeError('The declaration must honestly identify its post-primary-start timing')
    for path, config in configs:
        write_new(path, config)
    for row in slots:
        row['runtime_config_sha256'] = sha(row['runtime_config_file'])
    closure = {str(path.relative_to(ROOT)): sha(path) for path in [*mapping, *source_files, *(p for p, _ in configs)]}
    registration = {'schema_version': 1, 'diagnostic_id': 'unrestricted_paired_retestall',
        'phase': 'secondary_retestall', 'formal_registration': False, 'declared_at_utc': utc(),
        'validation_freeze_file': str(freeze), 'validation_freeze_sha256': sha(freeze),
        'guide_freeze_file': str(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'),
        'guide_freeze_sha256': sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'),
        'files_sha256': closure, 'query_cap_per_block': 48, 'total_query_cap': 192,
        'generation_allocation_ceiling_seconds': 2400,
        'native_lifetime_admission_reserve_seconds': 600, 'block_order': slots,
        'attribution': {'added_after_primary_main_started': True,
            'motivation': 'A complete cold selected trajectory allocates48 profile queries plus12/24 selected queries; warm adds16 own-history queries. Unrestricted paired retesting of8 tasks at3changes requires48 queries without profiling/history. Measure that separate engineering-cost tradeoff while preserving the hard K2/K4 primary comparison.',
            'not_K2_K4_budget_matched': True, 'counts_toward_primary_80': False,
            'cannot_rescue_primary_result': True},
        'primary_budget_master_file': str(RUN/'MAIN_BUDGET_MASTER.json'),
        'primary_budget_master_sha256': sha(RUN/'MAIN_BUDGET_MASTER.json'),
        'native_head_at_declaration': read(RUN/'NATIVE_HEAD.json'),
        'expected_cumulative_native_ceiling_if_all_primary_and_secondary_complete': 4938,
        'shared_native_cap_unchanged': 5000,
        'primary_main_performance_aggregates_reviewed_by_root_at_declaration': False,
        'new_native_queries_dispatched_by_registration': 0,
        'primary_matrix_or_success_criteria_changed': False,
        'history_profiles_reference_bank_or_new_prompt_tuning_used_by_diagnostic': False}
    write_new(registration_path, registration)
    digest = sha(registration_path)
    for path, stage in stages:
        slot = next(row for row in slots if row['stage_authority_file'] == str(path))
        stage.update(secondary_registration_sha256=digest,
                     runtime_config_sha256=slot['runtime_config_sha256'])
        write_new(path, stage)
    print({'registration': str(registration_path), 'sha256': digest,
           'new_native_queries': 0, 'primary_criteria_changed': False})


if __name__ == '__main__':
    main()

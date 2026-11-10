"""Seal reviewed results and already closed native accounting. No dispatch."""
from pathlib import Path
import argparse

from experiment.transfer_v9.common import ROOT, HERE, PRIOR, read, save, sha, utc, verify_foundation

REPORT_SHA = '830d1ace784b4f8abafd77b27b3a537baceeae5c0ad997da1f239e4a8cc921a0'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    prior = verify_foundation()
    report = ROOT/'experiment/RESULTS_TRANSFER_V9.md'
    if sha(report) != REPORT_SHA:
        raise RuntimeError('The report differs from the final independently reviewed bytes')
    readiness = read(run/'ANALYSIS_READINESS.json')
    if readiness['status'] != 'PASS' or not readiness['all_owned_helpers_closed']:
        raise RuntimeError('Native work must be audited, settled and closed')
    for relative, expected in readiness['bound_files_sha256'].items():
        if sha(ROOT/relative) != expected:
            raise RuntimeError('An audited or analyzed input changed')
    resource = read(run/'VALIDATION_RESOURCE_SUMMARY.json')
    actual = resource['settled_actual_resources']
    if actual['native_query_units'] != 189 or actual['queryfree_native_check_units'] != 188:
        raise RuntimeError('Unexpected final physical native accounting')
    if resource['unsettled_operation_ids'] or resource['over_cap_dimensions']:
        raise RuntimeError('Unsettled or over-budget resource work cannot be sealed complete')
    summary = read(run/'evaluation/SUMMARY.json')
    confirmation = read(run/'evaluation/SAME_CASE_CONFIRMATION.json')
    review = {'status': 'PASS_REVIEWED_REPORT', 'at_utc': utc(), 'report_sha256': REPORT_SHA,
        'report_bytes': report.stat().st_size,
        'review_scope': ['native/source/accounting numeric claims', 'replay and interaction contrasts',
                         'source-case independence and scope', 'native versus replay distinction',
                         'background failure', 'request versus wall/CPU units'],
        'review_method': 'Separate assistant implementations and read-only claim checks; not external human peer review',
        'both_final_reviews_bound_to_same_report_bytes': True,
        'source_data_or_frozen_core_changes_for_report': False}
    save(run/'REPORT_REVIEW.json', review)
    files = [report, run/'REPORT_REVIEW.json', run/'STUDY_FREEZE.json',
        run/'ENGINEERING_AMENDMENT_FREEZE.json', run/'RASA_DEPENDENCY_AMENDMENT_FREEZE.json',
        run/'RESOURCE_MANIFEST.json', run/'DEVELOPMENT_GATE.json', run/'VALIDATION_RESOURCE_SUMMARY.json',
        run/'OWNED_CLOSURE_CHECK.json', run/'ANALYSIS_READINESS.json',
        run/'accounting/events.jsonl', run/'accounting/HEAD.json',
        HERE/'audits/INDEPENDENT_COMPLETED_DEVELOPMENT_PY312.json',
        HERE/'audits/INDEPENDENT_COMPLETED_VALIDATION_PY312.json',
        run/'NATIVE_BANK.json', run/'FRESH_CONFIRMATION.json', run/'LIVE_POLICY_CONFIRMATION.json',
        run/'evaluation/SUMMARY.json', run/'evaluation/SAME_CASE_CONFIRMATION.json',
        run/'presentation/PRESENTATION_RECEIPT.json', run/'presentation_review/REVIEW_DERIVATIVE_RECEIPT.json']
    final = {'phase': 'TRANSFER_V9', 'at_utc': utc(),
        'status': 'NATIVE_AND_RECORDED_OUTCOME_ANALYSIS_COMPLETE_ALL_OWNED_HELPERS_CLOSED',
        'results_report_sha256': REPORT_SHA, 'report_path': report.relative_to(ROOT).as_posix(),
        'all_owned_helpers_closed': True,
        'prior_receipt_sha256': sha(PRIOR),
        'prior_closed_native_units': prior['native_units_cumulative'],
        'prior_closed_native_cap': 5000, 'prior_account_reopened_or_counters_reset': False,
        'native_observations_completed_this_phase': 376,
        'retained_failed_native_initialization_attempts': 1,
        'combined_native_attempts_this_phase': 377, 'combined_native_attempt_cap': 400,
        'generative_native_attempts_this_phase': actual['native_query_units'],
        'queryfree_native_observations_this_phase': actual['queryfree_native_check_units'],
        'generative_native_attempts_cumulative': resource['cumulative_native_query_units_committed'],
        'queryfree_new_dimension_not_equated_with_legacy_generation_units': True,
        'provider_chat_boundaries_this_phase': actual['provider_chat_units'],
        'generation_allocation_seconds_this_phase': actual['generation_allocation_seconds'],
        'instrumented_operation_interval_seconds_this_phase': actual['end_to_end_seconds'],
        'cumulative_generation_allocation_seconds': resource['cumulative_generation_allocation_seconds_committed'],
        'independently_sourced_upstream_cases': 4,
        'native_implementation_settings': 2,
        'physical_primary_native_records': summary['physical_primary_native_records'],
        'fresh_same_case_fourth_pass_records': confirmation['fresh_confirmation_records'],
        'fresh_live_policy_cells': 4, 'fresh_live_policy_native_requests': 88,
        'primary_counterfactual_trajectories': summary['primary_counterfactual_trajectories'],
        'secondary_amortization_counterfactual_trajectories': summary['secondary_amortization_counterfactual_trajectories'],
        'counterfactual_decisions': summary['all_counterfactual_decisions'],
        'new_native_or_provider_calls_in_replay_finalization': 0,
        'all_case_replacements_or_guidance_tuning_after_validation': False,
        'complete_application_level_external_validation_or_portable_superiority_established': False,
        'artifact_verification_recorded_separately_after_sealing': True,
        'evidence': {p.relative_to(ROOT).as_posix(): sha(p) for p in files}}
    save(run/'FINAL_ACCOUNTING_AND_CLEANUP.json', final)


if __name__ == '__main__':
    main()

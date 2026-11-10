"""Describe the separate RetestAll observations against the saved reference bank.

Pure saved-data analysis. This is not a primary arm, K-matched comparison, or a
change to any of the original selection-utility/retention criteria.
"""
from pathlib import Path
import argparse
import csv
import json
from experiment.development_v8.secondary_retestall import ORDER, evaluate_saved, read, sha


def describe(run, primary_summary):
    run = Path(run).resolve()
    primary = read(primary_summary)
    if primary.get('complete_frozen_frame') is not True or primary.get('trajectory_count') != 80:
        raise ValueError('Full primary evaluation is required for the separately acquired truth bank')
    registration = run/'SECONDARY_RETESTALL_REGISTRATION.json'; document = read(registration)
    if [(slot['app'], slot['repetition']) for slot in document['block_order']] != list(ORDER):
        raise ValueError('All four declared diagnostic slots are required')
    rows = []; sources = {str(registration): sha(registration), str(Path(primary_summary).resolve()): sha(primary_summary)}
    for slot in document['block_order']:
        app, rep = slot['app'], slot['repetition']; directory = Path(slot['output_dir'])
        if directory.resolve() != run/f'secondary-retestall-{app}-r{rep}':
            raise ValueError('Unexpected diagnostic output slot')
        completion = read(directory/'SECONDARY_COMPLETION.json')
        if completion['registration_sha256'] != sha(registration):
            raise ValueError('Diagnostic completion belongs to another declaration')
        replay = evaluate_saved(directory)
        truth = {(row['episode_index'], row['task_id']): row['classification']
                 for row in primary['applications'][app]['reference_cells']}
        if len(truth) != 24 or any(value in ('uncertain', 'incomplete') for value in truth.values()):
            raise ValueError('Complete stable24-cell reference frame required')
        targets = {key for key, value in truth.items() if value == 'regression'}
        alarms = {(row['episode_index'], row['task_id']) for row in replay['pairs'] if row['unrestricted_alarm']}
        usage = completion['physical_usage']
        rows.append({'application': app, 'repetition': rep,
            'detected': len(targets & alarms), 'reference_regression_cells': len(targets),
            'fault_A_detected': sum(key[0] == 1 for key in targets & alarms),
            'fault_B_detected': sum(key[0] == 3 for key in targets & alarms),
            'reference_discordant_alarms': len(alarms-targets),
            'repair_alarms': sum(truth[key] == 'repair' for key in alarms),
            'own_pair_reference_mismatches': sum(
                ('regression' if row['old_check']['primary_pass'] and not row['new_check']['primary_pass'] else
                 'repair' if not row['old_check']['primary_pass'] and row['new_check']['primary_pass'] else
                 'preserved_correct' if row['old_check']['primary_pass'] else 'persistent_failure')
                != truth[(row['episode_index'], row['task_id'])] for row in replay['pairs']),
            'native_queries': usage['native_query_units'], 'provider_chat_boundaries': usage['provider_chat_boundaries'],
            'embedding_boundaries': usage['embedding_boundaries'],
            'generation_allocation_seconds': usage['gpu_allocation_seconds'],
            'observed_dedicated_block_wall_seconds': completion['wall_seconds'],
            'K_budget_matched': False, 'counts_toward_primary_80': False})
        sources[str(directory/'SECONDARY_COMPLETION.json')] = sha(directory/'SECONDARY_COMPLETION.json')
    return {'scope': 'Additional unrestricted paired full-suite diagnostic, declared after primary execution started.',
            'rows': rows, 'detected': sum(row['detected'] for row in rows),
            'reference_regression_cells': sum(row['reference_regression_cells'] for row in rows),
            'native_queries': sum(row['native_queries'] for row in rows),
            'primary_result_changed': False, 'K_budget_matched': False,
            'standalone_primary_wall_is_allocated_component_sum_while_secondary_wall_is_dedicated_later_block': True,
            'causal_wall_speedup_or_population_significance_claim': False,
            'source_sha256': sources, 'presentation_source_sha256': sha(Path(__file__)),
            'new_native_or_provider_queries': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--primary-summary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); result = describe(args.run, args.primary_summary)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output/'SECONDARY_SUMMARY.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    with (args.output/'SECONDARY_TABLE.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result['rows'][0]))
        writer.writeheader(); writer.writerows(result['rows'])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

"""Presentation tables from the complete, independently checked primary summary.

This does not change judgments, thresholds, selection rules or success criteria.
The public artifact's reanalysis entry point independently recomputes the source
summary before these optional presentation tables are interpreted.
"""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import csv
import hashlib
import json

ARMS = ('I0_H0', 'I1_H0', 'I0_H1', 'I1_H1', 'CG1')


def present(summary):
    if summary.get('complete_frozen_frame') is not True or summary.get('trajectory_count') != 80:
        raise ValueError('A complete80-trajectory primary evaluation is required')
    groups = defaultdict(list); chosen = defaultdict(Counter)
    for row in summary['trajectories']:
        key = (row['application_id'], row['budget_id'], row['history_regime'], row['arm'])
        groups[key].append(row)
        if row['arm'] == 'CG1':
            chosen[row['application_id']].update(row['chosen_arm_distribution'])
    rows = []
    for app in ('openwebui', 'dify'):
        for budget in ('LOW', 'HIGH'):
            for regime in ('COLD', 'WARM'):
                for arm in ARMS:
                    values = groups[(app, budget, regime, arm)]
                    if len(values) != 2 or {row['repetition'] for row in values} != {1, 2}:
                        raise ValueError('Missing/duplicated primary repetition')
                    total = lambda name: sum(row[name] for row in values)
                    family = lambda episode, name: sum(part[name] for row in values
                        for part in row['per_episode'] if part['episode_index'] == episode)
                    rows.append({'application': app, 'K': 2 if budget == 'LOW' else 4,
                        'history': regime, 'method': arm, 'execution_repetitions': 2,
                        'detected': total('detected'), 'reference_regression_cells': total('reference_regression_cells'),
                        'fault_A_detected': family(1, 'detected'), 'fault_A_cells': family(1, 'target_cells'),
                        'fault_B_detected': family(3, 'detected'), 'fault_B_cells': family(3, 'target_cells'),
                        'reference_discordant_alarms': total('reference_discordant_alarms'),
                        'repair_alarms': total('repair_alarms'),
                        'selected_pairs': total('selected_comparison_pairs'),
                        'timely_pairs': total('timely_comparison_pairs'),
                        'schedule_deviations': total('nominal_actual_schedule_deviations'),
                        'own_pair_reference_mismatches': sum(len(row['own_pair_reference_mismatches']) for row in values),
                        'source_recheck_mismatches': sum(len(row['source_recheck_mismatches']) for row in values),
                        'allocated_native_queries_per_trajectory_min': min(row['allocated_standalone_native_query_units'] for row in values),
                        'allocated_native_queries_per_trajectory_max': max(row['allocated_standalone_native_query_units'] for row in values),
                        'allocated_wall_seconds_per_trajectory_min': min(row['allocated_standalone_wall_seconds'] for row in values),
                        'allocated_wall_seconds_per_trajectory_max': max(row['allocated_standalone_wall_seconds'] for row in values)})
    return {'rows': rows, 'CG1_chosen_arm_counts_by_application': {app: dict(value) for app, value in chosen.items()},
            'primary_criteria': {key: summary[key] for key in ('prospective_directional_retention',
                'prospective_selection_utility', 'family_specific_loss_present', 'interpretation')},
            'observations_are_repeated_task_change_opportunities_not_independent_defects': True,
            'new_native_or_provider_queries': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.summary.read_bytes(); summary = json.loads(raw.decode('utf-8-sig'))
    result = present(summary)
    result['input_summary_sha256'] = hashlib.sha256(raw).hexdigest()
    result['presentation_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output/'PRIMARY_TABLES.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    with (args.output/'COMPARISONS.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result['rows'][0]))
        writer.writeheader(); writer.writerows(result['rows'])
    print(json.dumps(result['primary_criteria']))
    for app in ('openwebui', 'dify'):
        for k in (2, 4):
            for regime in ('COLD', 'WARM'):
                values = [row for row in result['rows'] if (row['application'], row['K'], row['history']) == (app, k, regime)]
                print(f'{app} K{k} {regime}: '+', '.join(
                    f'{row["method"]} {row["detected"]}/{row["reference_regression_cells"]}' for row in values))


if __name__ == '__main__':
    main()

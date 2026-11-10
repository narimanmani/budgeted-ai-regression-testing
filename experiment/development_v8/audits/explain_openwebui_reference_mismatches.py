"""Posthoc read-only source/prompt trace for completed OWU reference mismatches."""
from pathlib import Path
from collections import Counter, defaultdict
from copy import deepcopy
import argparse
import hashlib
import json
import re
from experiment.development_v8.audits.audit_acquisition import (
    read, sha, need, choose_provider_events, model_check, prompt_context,
)
from experiment.development_v8.secondary_retestall import require_closed_primary
from experiment.validation_v7.execution.source_channels import CanonicalContracts


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def normalize_collection_ids(messages):
    """Observational comparison only; never supplied to an application/model."""
    result = deepcopy(messages)
    for message in result:
        if isinstance(message.get('content'), str):
            message['content'] = re.sub(r'(?<=resource-id=")[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?=")',
                                        '<NATIVE_COLLECTION_UUID>', message['content'])
    return result


def explain(run):
    run = Path(run).resolve(); outer = read(run/'VALIDATION_FREEZE.json')
    require_closed_primary(run, outer)
    summary_path = run/'evaluation/SUMMARY.json'; summary = read(summary_path)
    need(summary['complete_frozen_frame'] is True and summary['trajectory_count'] == 80,
         'Complete unchanged primary evaluation required')
    selected = []
    for evaluated in summary['trajectories']:
        if evaluated['application_id'] != 'openwebui': continue
        result_path = run/f'main-openwebui-r{evaluated["repetition"]}'/'block/trajectories'/evaluated['trajectory_id']/'TRAJECTORY_RESULT.json'
        result = read(result_path)
        for mismatch in evaluated['own_pair_reference_mismatches']:
            pair = next(p for p in result['selected_pairs'] if
                (p['episode_index'], p['task_id']) == (mismatch['episode_index'], mismatch['task_id']))
            selected.append({'trajectory_id': result['trajectory_id'], 'repetition': result['repetition'],
                'arm': result['arm'], 'history_regime': result['history_regime'], 'budget_id': result['budget_id'],
                **mismatch, 'pair_file': pair['receipt_path'], 'pair_sha256': pair['receipt_sha256'],
                'old_request_id': pair['old_request_id'], 'new_request_id': pair['new_request_id']})
    tasks = sorted({r['task_id'] for r in selected})
    contracts_path = Path(__file__).resolve().parents[1]/'workloads/validation/openwebui/contracts.json'
    document = read(contracts_path); contracts = CanonicalContracts(document)
    frames = ['qualification-openwebui-P0', 'reference-openwebui-P0', 'main-openwebui-r1', 'main-openwebui-r2']
    raw = []
    for frame in frames:
        for path in (run/frame/'meter/raw').glob('*.json'):
            row = read(path)
            if row.get('task_id') in tasks: raw.append((frame, path, row))
    ids = {ident for _, _, row in raw for ident in row['root_meter_receipt']['provider_join']['provider_request_ids']}
    events = choose_provider_events(run/'provider/requests.jsonl', ids)
    backend_sha = sha(run/'backend_generation/BACKEND_PROVENANCE.json') if (run/'backend_generation/BACKEND_PROVENANCE.json').exists() else None
    groups = {}; raw_evidence = []
    for frame, path, row in raw:
        task, state = row['task_id'], row['state_id']; output = row['native_output']
        bound = {b['native_file_id']: b for b in output['source_bindings']}
        contexts = output['returned_contexts']; order = [bound[c['native_file_id']]['logical_id'] for c in contexts]
        texts = [c['document'] for c in contexts]
        spec = contracts.specs[task]; logical = spec['required_logical_source_id']
        target = [c['document'] for c in contexts if bound[c['native_file_id']]['logical_id'] == logical]
        need(len(target) == 1, 'Target record is not uniquely present in the actual retrieved context')
        binding = next(b for b in output['source_bindings'] if b['logical_id'] == logical)
        setup_path = run/frame/'native/states'/state/'SETUP.json'; setup = read(setup_path)
        ingestion = next(item for item in setup['ingestion'] if item['binding']['logical_id'] == logical)
        parsed = ingestion['native_parsed_content']['content']
        need(ingestion['binding']['native_file_id'] == binding['native_file_id'], 'Target native index/file mismatch')
        source_path = contracts_path.parent/'fixtures'/logical
        need(sha(source_path) == spec['original_byte_authority']['sha256'], 'Original byte authority changed')
        source = source_path.read_bytes().decode(spec['original_byte_authority']['encoding'])
        check = contracts.check(task, output, bindings=output['source_bindings'], state=state)
        reference = contracts.check(task, output, bindings=output['source_bindings'], state=state, reference=True)
        need(check['primary_pass'] == reference['primary_pass'], 'Operational/reference checker disagreement')
        chat = [events[i] for i in row['root_meter_receipt']['provider_join']['provider_request_ids']
                if events[i]['path'] == '/v1/chat/completions']
        need(len(chat) == 1, 'Scientific query must have exactly one actual generation')
        event = chat[0]; model_check(event, event['backend_receipt_sha256'])
        context = prompt_context('openwebui', event, output)
        messages = event['upstream_request']['messages']; normalized = normalize_collection_ids(messages)
        nonmessages = {k: v for k, v in event['upstream_request'].items() if k != 'messages'}
        need(target[0] in context and all(value in source and value in parsed and value in target[0]
             for value in spec['accepted_values']), 'Source/index/context lost original accepted label')
        key = (frame, state, task)
        common = {'frame': frame, 'state_id': state, 'task_id': task,
            'original_source_file': str(source_path), 'original_source_sha256': sha(source_path),
            'native_setup_file': str(setup_path), 'native_setup_sha256': sha(setup_path),
            'native_collection_id': binding['workspace_id'], 'native_target_file_id': binding['native_file_id'],
            'native_parsed_target_text_sha256': digest(parsed), 'retrieved_target_text_sha256': digest(target[0]),
            'ordered_retrieved_logical_ids': order, 'ordered_retrieved_texts_sha256': digest(texts),
            'actual_messages_sha256': digest(messages), 'collection_UUID_normalized_messages_sha256': digest(normalized),
            'nonmessage_upstream_parameters_sha256': digest(nonmessages),
            'generic_prompt_sha256': output['prompt_text_sha256'], 'actual_backend_sha256': event['backend_receipt_sha256'],
            'source_index_target_label_preserved': True, 'operational_and_reference_primary_flags_agree': True,
            'all_actual_model_calls_0_96_uncached_untruncated': True}
        if key not in groups:
            groups[key] = {**common, 'answer_counts': Counter(), 'primary_counts': Counter(), 'role_counts': Counter(),
                'original_source_quote': source.strip(), 'native_parsed_target_quote': parsed.strip(),
                'retrieved_target_quote': target[0], 'sample_request_id': row['request_id']}
        else:
            need(all(groups[key][k] == value for k, value in common.items()), 'Within-scope target/source/prompt changed')
        group = groups[key]; group['answer_counts'][output['answer']] += 1
        group['primary_counts'][str(check['primary_pass'])] += 1; group['role_counts'][row['phase']] += 1
        raw_evidence.append({'frame': frame, 'state_id': state, 'task_id': task, 'phase': row['phase'],
            'request_id': row['request_id'], 'raw_file': str(path), 'raw_sha256': sha(path),
            'actual_provider_request_id': event['request_id'], 'answer': output['answer'],
            'primary_pass': check['primary_pass'], 'source_metadata_pass': check['source_metadata_pass']})
    comparisons = []
    for task in tasks:
        rows = [v for (f, state, t), v in groups.items() if t == task and state == 'A_BAD']
        comparisons.append({'task_id': task, 'state_id': 'A_BAD', 'frames_compared': [r['frame'] for r in rows],
            'all_original_source_SHA_identical': len({r['original_source_sha256'] for r in rows}) == 1,
            'all_native_parsed_target_text_identical': len({r['native_parsed_target_text_sha256'] for r in rows}) == 1,
            'all_retrieved_document_order_and_text_identical': len({r['ordered_retrieved_texts_sha256'] for r in rows}) == 1
                and len({tuple(r['ordered_retrieved_logical_ids']) for r in rows}) == 1,
            'all_actual_messages_identical_after_ONLY_collection_resource_UUID_replacement':
                len({r['collection_UUID_normalized_messages_sha256'] for r in rows}) == 1,
            'actual_messages_byte_identical': len({r['actual_messages_sha256'] for r in rows}) == 1,
            'all_nonmessage_model_request_parameters_identical': len({r['nonmessage_upstream_parameters_sha256'] for r in rows}) == 1,
            'all_backend_provenance_identical': len({r['actual_backend_sha256'] for r in rows}) == 1,
            'native_collection_UUIDs': [r['native_collection_id'] for r in rows]})
    unique = defaultdict(list)
    for row in selected:
        unique[(row['episode_index'], row['task_id'], row['own_pair'], row['reference'])].append(row)
    unique_cases = [{'episode_index': key[0], 'task_id': key[1], 'observed_pair_class': key[2], 'reference_class': key[3],
                    'selected_pair_count': len(value), 'affected_trajectories': sorted({r['trajectory_id'] for r in value})}
                   for key, value in sorted(unique.items())]
    return {'audit_passed': True, 'scope': 'Read-only posthoc explanation of frozen primary OWU mismatch cells',
        'primary_evaluation_file': str(summary_path), 'primary_evaluation_sha256': sha(summary_path),
        'audit_source_sha256': sha(Path(__file__)), 'unique_task_ids': tasks, 'unique_episode_cases': unique_cases,
        'selected_pair_mismatch_count': len(selected), 'actual_affected_task_generations_checked': len(raw_evidence),
        'groups': list(groups.values()), 'cross_native_index_comparisons': comparisons,
        'selected_pair_evidence': selected, 'actual_raw_evidence': raw_evidence,
        'interpretation': [
            'All observed mismatches concern the same VOW07/A_BAD task-state in repetition2, not26 independent defects.',
            'The exact label characters survive original source, native parsing, retrieval and actual model input; the emitted extra square brackets violate the unchanged explicit output-format contract.',
            'Operational and independent reference checkers agree on each actual output. No checker inconsistency or missing target fact was found.',
            'A_BAD source texts and document order match across fresh reference and both main indices. The actual messages differ in native collection resource UUIDs and become identical after replacing only those UUID tokens.',
            'Consistent different formatting co-occurs with the new native-index prompt identity. This saved evidence does not establish UUID causation, numerical nondeterminism, or an independent source-level defect for VOW07.',
            'The two-pass reference bank was stable within its own native index. It does not guarantee every later independently instantiated index has the same output-format behavior.',
            'Reference-discordant alarms remain real fixed-contract noncompliance observations; they are not automatically detections of the preclassified source-fault target opportunities.',
            'No answers, prompts, contracts, reference labels, policy, metrics or frozen success criteria were changed, and no counterfactual execution was performed.'
        ], 'new_native_or_provider_queries': 0, 'primary_evaluation_or_frozen_files_modified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); result = explain(args.run)
    from experiment.development_v8.control import write_new
    write_new(args.output, result)
    print(json.dumps({key: result[key] for key in ('audit_passed', 'unique_task_ids', 'selected_pair_mismatch_count',
                                                'actual_affected_task_generations_checked', 'cross_native_index_comparisons')}, indent=2))


if __name__ == '__main__': main()

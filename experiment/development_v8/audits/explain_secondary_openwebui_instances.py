"""Descriptive fresh-index follow-up using already completed diagnostic queries.

No native execution, no altered reference labels and no primary rescoring.
"""
from pathlib import Path
from collections import Counter
import argparse
from experiment.development_v8.audits.audit_acquisition import (
    read, sha, need, model_check, prompt_context, choose_provider_events, audit_sources,
)
from experiment.development_v8.audits.explain_openwebui_reference_mismatches import digest, normalize_collection_ids
from experiment.development_v8.control import write_new
from experiment.validation_v7.execution.source_channels import CanonicalContracts


def audit(run):
    run = Path(run).resolve(); frames = [f'secondary-retestall-{app}-r{rep}'
        for app, rep in [('openwebui', 1), ('dify', 1), ('openwebui', 2), ('dify', 2)]]
    for frame in frames:
        completion = read(run/frame/'SECONDARY_COMPLETION.json')
        need(completion['success'] is True and completion['complete'] is True and completion['error'] is None
             and completion['native_queries'] == 48 and completion['completed_pairs'] == 24,
             'All four locked secondary blocks must finish before the descriptive follow-up')
    base_path = run/'audits/OPENWEBUI_REFERENCE_MISMATCH_FORENSICS.json'; base = read(base_path)
    originals = [g for g in base['groups'] if g['state_id'] == 'A_BAD' and g['task_id'] == 'VOW07']
    need(len(originals) == 3, 'Three completed original A_BAD prompt-index groups required')
    case = Path(__file__).resolve().parents[1]/'workloads/validation/openwebui'
    contracts = CanonicalContracts(read(case/'contracts.json'))
    sources = {r['logical_id']: r for r in read(case/'source_manifest.json')['sources']}
    selected = []
    for frame in [frames[0], frames[2]]:
        for path in (run/frame/'meter/raw').glob('*.json'):
            raw = read(path)
            if raw['task_id'] == 'VOW07': selected.append((frame, path, raw))
    ids = {i for _, _, r in selected for i in r['root_meter_receipt']['provider_join']['provider_request_ids']}
    events = choose_provider_events(run/'provider/requests.jsonl', ids)
    expected_backend = read(run/'CAMPAIGN_AUTH.json')['backend_receipt_sha256']
    groups = {}; observed = []; source_proofs = {}
    for frame, path, raw in selected:
        native = raw['native_output']; state = raw['state_id']; bindings = native['source_bindings']
        key = (frame, state)
        if key not in source_proofs:
            source_proofs[key] = audit_sources('openwebui', state, bindings, sources)
        mapping = {b['native_file_id']: b for b in bindings}
        binding = next(b for b in bindings if b['logical_id'] == 'vow07.txt')
        contexts = native['returned_contexts']; texts = [c['document'] for c in contexts]
        order = [mapping[c['native_file_id']]['logical_id'] for c in contexts]
        target = [c['document'] for c in contexts if mapping[c['native_file_id']]['logical_id'] == 'vow07.txt']
        need(target == ['Record VOW07 access label [TERRACE-703]'], 'Target record changed in retrieved content')
        setup_path = run/frame/'native/states'/state/'SETUP.json'; setup = read(setup_path)
        indexed = next(x for x in setup['ingestion'] if x['binding']['logical_id'] == 'vow07.txt')
        need(indexed['binding']['native_file_id'] == binding['native_file_id']
             and indexed['native_parsed_content']['content'] == 'Record VOW07 access label [TERRACE-703]\n',
             'Fresh native parsed/indexed target differs from original authority')
        chat = [events[i] for i in raw['root_meter_receipt']['provider_join']['provider_request_ids']
                if events[i]['path'] == '/v1/chat/completions']
        need(len(chat) == 1, 'Exactly one actual generation per fresh native query required')
        event = chat[0]; model_check(event, expected_backend); prompt_context('openwebui', event, native)
        checked = contracts.check('VOW07', native, bindings=bindings, state=state)
        independent = contracts.check('VOW07', native, bindings=bindings, state=state, reference=True)
        need(checked['primary_pass'] == independent['primary_pass'], 'Checker disagreement')
        messages = event['upstream_request']['messages']
        view = {'frame': frame, 'state_id': state, 'native_collection_id': binding['workspace_id'],
            'native_target_file_id': binding['native_file_id'], 'native_setup_file': str(setup_path),
            'native_setup_sha256': sha(setup_path), 'ordered_retrieved_logical_ids': order,
            'ordered_retrieved_texts_sha256': digest(texts), 'actual_messages_sha256': digest(messages),
            'collection_UUID_normalized_messages_sha256': digest(normalize_collection_ids(messages)),
            'nonmessage_upstream_parameters_sha256': digest({k:v for k,v in event['upstream_request'].items() if k!='messages'}),
            'target_fact_preserved_source_to_index_context_and_model': True}
        if key not in groups: groups[key] = {**view, 'answer_counts': Counter(), 'primary_counts': Counter()}
        else: need(all(groups[key][k] == value for k, value in view.items()), 'Within-index prompt changed')
        groups[key]['answer_counts'][native['answer']] += 1
        groups[key]['primary_counts'][str(checked['primary_pass'])] += 1
        observed.append({'frame': frame, 'state_id': state, 'request_id': raw['request_id'],
            'raw_file': str(path), 'raw_sha256': sha(path), 'actual_provider_request_id': event['request_id'],
            'answer': native['answer'], 'primary_pass': checked['primary_pass']})
    combined = [*originals, *[g for (_, state), g in groups.items() if state == 'A_BAD']]
    return {'audit_passed': True, 'scope': 'Posthoc descriptive new native-index instances from prospectively locked secondary diagnostic',
        'base_forensic_file': str(base_path), 'base_forensic_sha256': sha(base_path),
        'secondary_registration_sha256': sha(run/'SECONDARY_RETESTALL_REGISTRATION.json'),
        'same_A_BAD_source_text_and_order_in_all_five_indices': len({g['ordered_retrieved_texts_sha256'] for g in combined}) == 1
            and len({tuple(g['ordered_retrieved_logical_ids']) for g in combined}) == 1,
        'same_A_BAD_model_messages_after_ONLY_collection_UUID_normalization_in_all_five_indices':
            len({g['collection_UUID_normalized_messages_sha256'] for g in combined}) == 1,
        'same_nonmessage_parameters_in_all_five_indices': len({g['nonmessage_upstream_parameters_sha256'] for g in combined}) == 1,
        'A_BAD_index_instances': [{'frame':g['frame'],'native_collection_id':g['native_collection_id'],
            'answer_counts':g['answer_counts'],'primary_counts':g['primary_counts']} for g in combined],
        'new_secondary_task_generations': len(observed), 'groups': list(groups.values()), 'raw_evidence': observed,
        'source_proofs': list(source_proofs.values()), 'all_actual_model_calls_0_96_uncached_untruncated_and_authorized_backend': True,
        'causation_established': False, 'new_native_or_provider_queries': 0,
        'primary_metrics_reference_labels_contracts_or_frozen_criteria_changed': False,
        'interpretation': 'These are additional descriptive instances of native prompt/index identity, not a randomized UUID intervention or a new primary comparison.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); result = audit(args.run); write_new(args.output, result)
    print({key:result[key] for key in ('audit_passed','new_secondary_task_generations','same_A_BAD_source_text_and_order_in_all_five_indices',
        'same_A_BAD_model_messages_after_ONLY_collection_UUID_normalization_in_all_five_indices','A_BAD_index_instances')})

from experiment.development_v8.audits.explain_openwebui_reference_mismatches import normalize_collection_ids


def test_only_native_resource_UUID_changes_are_normalized_without_mutating_evidence():
    first=[{'role':'user','content':'<source resource-id="81205848-22a4-4f5b-85b9-1d9276fd70f8">Record VOW07 [TERRACE-703]</source>'}]
    second=[{'role':'user','content':'<source resource-id="a27d6867-e1ad-4791-b13d-2880f6fd4247">Record VOW07 [TERRACE-703]</source>'}]
    assert normalize_collection_ids(first)==normalize_collection_ids(second)
    assert '81205848-' in first[0]['content']
    changed=[{'role':'user','content':second[0]['content'].replace('TERRACE-703','OTHER-703')}]
    assert normalize_collection_ids(first)!=normalize_collection_ids(changed)


def test_source_order_and_unrelated_UUID_tokens_remain_observable():
    a=[{'role':'user','content':'Record A\nRecord B resource-id="81205848-22a4-4f5b-85b9-1d9276fd70f8"'}]
    b=[{'role':'user','content':'Record B\nRecord A resource-id="a27d6867-e1ad-4791-b13d-2880f6fd4247"'}]
    assert normalize_collection_ids(a)!=normalize_collection_ids(b)
    assert normalize_collection_ids([{'content':'plain UUID 81205848-22a4-4f5b-85b9-1d9276fd70f8'}]) != normalize_collection_ids([{'content':'plain UUID a27d6867-e1ad-4791-b13d-2880f6fd4247'}])

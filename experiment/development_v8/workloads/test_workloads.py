"""Independent source-byte and separation checks; no application dispatch."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re

from experiment.native_v3.common.contracts import operational_check
from experiment.native_v3.common.reference import reference_check

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def groups():
    for cohort in ('development','validation'):
        for app in ('dify','openwebui'):
            yield cohort,app,HERE/cohort/app

def test_every_contract_is_uniquely_authorized_by_original_bytes():
    for cohort,app,directory in groups():
        docs=read(directory/'source_manifest.json');contracts=read(directory/'contracts.json')['contracts']
        assert docs['sources']==docs['documents']
        sources={r['logical_id']:r for r in docs['sources']}
        tasks=read(directory/'tasks.json')['tasks']
        assert len(sources)==len(contracts)==len(tasks)==8
        assert {t['id'] for t in tasks}=={c['id'] for c in contracts}
        for contract in contracts:
            source=sources[contract['required_logical_source_id']];path=directory/source['file']
            assert sha(path)==source['sha256']==contract['original_byte_authority']['sha256']
            assert len(path.read_bytes())==source['bytes']
            text=path.read_bytes().decode(source['encoding'],errors='strict')
            labels=re.findall(r'\[([^\[\]]+)\]',text)
            assert labels==contract['accepted_values']
            assert re.findall(r'\bRecord\s+([A-Z0-9]+)\s+access label',text)==[contract['id']]

def test_development_validation_and_v7_facts_and_ids_are_disjoint():
    facts={};identities={}
    for cohort,app,directory in groups():
        contracts=read(directory/'contracts.json')['contracts']
        facts[cohort,app]={v for c in contracts for v in c['accepted_values']}
        identities[cohort,app]={c['id'] for c in contracts}
    for first in facts:
        for second in facts:
            if first!=second:
                assert not facts[first]&facts[second]
                assert not identities[first]&identities[second]
    old=[]
    for name in ('experiment/validation_v7/dify/inputs/contracts.json','experiment/validation_v7/openwebui/contracts.json'):
        old.extend(read(ROOT/name)['contracts'])
    oldvalues={v for c in old for v in c['accepted_values']};oldids={c['id'] for c in old}
    assert not oldvalues&set.union(*facts.values())
    assert not oldids&set.union(*identities.values())

def test_questions_and_generic_prompt_candidates_do_not_contain_gold():
    prompts=read(HERE/'prompts.json')
    assert prompts['selection_order']==['P0','P1']
    assert [p['id'] for p in prompts['candidates']]==['P0','P1']
    assert [p['order'] for p in prompts['candidates']]==[0,1]
    generic=' '.join(p['prompt_text'] for p in prompts['candidates'])
    for _,_,directory in groups():
        contracts=read(directory/'contracts.json')['contracts'];tasks=read(directory/'tasks.json')['tasks']
        for c in contracts:
            assert c['id'] not in generic
            for v in c['accepted_values']:
                assert v not in generic
                assert all(v not in t['question'] for t in tasks)

def test_predeclared_witnesses_controls_and_case_counts():
    for _,_,directory in groups():
        q=read(directory/'qualification.json');ids=q['task_ids']
        assert len(ids)==len(set(ids))==8
        assert q['qualification_witnesses']=={'A_BAD':ids[0],'B_BAD':ids[2]}
        assert q['qualification_subsets']=={'A_BAD':[ids[i] for i in (0,1,4,5)],'B_BAD':[ids[i] for i in (2,3,4,5)]}
        assert q['unaffected_controls']==ids[4:6]
        assert q['development_native_query_plan']['queries_per_prompt_candidate']==48
        assert q['validation_qualification_query_plan']['queries']==32

def test_dify_native_splitter_preconditions_and_unicode_target_are_present():
    for cohort in ('development','validation'):
        directory=HERE/cohort/'dify';docs=read(directory/'source_manifest.json')['sources']
        for index,doc in enumerate(docs):
            text=(directory/doc['file']).read_bytes().decode('utf-8')
            assert len(text)>80
            assert '\n' not in text and '. ' not in text
            label=re.search(r'\[([^\]]+)\]',text)
            assert label.end()<=50
            if index<2:assert '\u00ef' in label.group(1)
            elif index<4:assert ' ' in label.group(1) and label.group(1).isascii()
            else:assert label.group(1).isascii() and ' ' not in label.group(1)

def test_generator_is_deterministic_and_refuses_input_overwrite(tmp_path):
    spec=importlib.util.spec_from_file_location('_v8_workload_generator',HERE/'generate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for cohort,app,directory in groups():
        first=module.make_rows(cohort,app);second=module.make_rows(cohort,app)
        assert first==second
        assert [r['raw'] for r in first]==[(directory/'fixtures'/(r['id'].lower()+'.txt')).read_bytes() for r in first]
    sample=tmp_path/'input.txt';module.write_once(sample,b'first');module.write_once(sample,b'first')
    try:module.write_once(sample,b'different')
    except FileExistsError:pass
    else:raise AssertionError('Original bytes could be overwritten')

def test_recorded_source_projections_and_primary_judgments_match_partition():
    proof=read(HERE/'COMPONENT_PREFLIGHT.json')
    assert proof['native_or_model_calls']==0 and proof['all_source_sensitivities_pass']
    assert len(proof['results'])==32
    for result in proof['results']:
        directory=HERE/result['cohort']/result['application_id']
        contract=next(c for c in read(directory/'contracts.json')['contracts'] if c['id']==result['task_id'])
        primary={'id':contract['id'],'version':'v1','expected_behavior':'answer','accepted_answers':contract['accepted_values']}
        for state,value in result['component_observed_labels'].items():
            output={'answer':value,'completed':value is not None,'sources':[]}
            expected=result['expected_component_label_present'][state]
            assert operational_check(output,primary)['passed']==expected
            assert reference_check(output,primary)['passed']==expected

def test_all_generated_hashes_match_and_frozen_guide_is_unchanged():
    frame=read(HERE/'GENERATION_FRAME.json');files=read(HERE/'WORKLOAD_FILES.json')['files_sha256']
    assert frame['generator_source_sha256']==sha(HERE/'generate.py')
    assert frame['same_applications_and_historical_fault_families_as_v7'] is True
    assert read(HERE/'WORKLOAD_FILES.json')['native_or_model_outputs_seen_during_generation']==0
    assert all(sha(ROOT/name)==value for name,value in files.items())
    assert sha(ROOT/'experiment/validation_v7/guidance/policy.py')=='f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989'

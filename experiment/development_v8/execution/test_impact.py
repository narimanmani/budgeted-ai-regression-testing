"""Synthetic native/root receipts only; no application/model operation."""
from copy import deepcopy
from pathlib import Path
import json
import shutil

import pytest

from experiment.development_v8.execution import impact
from experiment.validation_v7.guidance import policy

ROOT=Path(__file__).resolve().parents[3]
SCOPE={'cohort_id':'validation','prompt_candidate_id':'P0',
       'prompt_text_sha256':'a'*64,'input_freeze_sha256':'b'*64}

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,indent=2,ensure_ascii=True)+'\n').encode())

def fixture(tmp_path,app='dify',state='HEALTHY',*,binding_invalid=False):
    episode=2 if state=='A_BAD' else 1
    model=impact._source_model(app,state)
    original=ROOT/'experiment/development_v8/workloads/validation'/app
    cohort=tmp_path/'cohort';cohort.mkdir()
    source=impact.read(original/'source_manifest.json')
    for item in source['sources']:
        target=cohort/item['file'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original/item['file'],target)
    manifest=cohort/'source_manifest.json';write(manifest,source)
    verify=tmp_path/'native_source_verification.json'
    if app=='openwebui':
        value={'checked':model['expected_count'],'mismatches':[],'state':state,
               'fixed_revision':model['cases']['fixed_revision'],'permitted_override_paths':model['override_paths']}
    else:value={'state_id':state,'verification':{'checked':model['expected_count'],'mismatches':[]},
                'expected_source_map_sha256':model['expected_map_sha256']}
    write(verify,value)
    config=tmp_path/'native_configuration.json';write(config,{**SCOPE,'state_id':state,'synthetic_receipt':True})
    bindings=[]
    for index,item in enumerate(source['sources']):
        binding={'state_id':state,'indexed':True,'logical_id':item['logical_id'],
            'logical_source_id':item['logical_id'],'version':'v1','native_id':f'doc{index}',
            'original_sha256':item['sha256'],'workspace_id':'native-workspace',
            'source_verification_path':str(verify),'source_verification_sha256':impact.sha(verify),
            'source_manifest_path':str(model['case_path']),'source_manifest_sha256':impact.sha(model['case_path']),
            'cohort_source_manifest_path':str(manifest),'cohort_source_manifest_sha256':impact.sha(manifest)}
        if app=='openwebui':binding.update(native_file_id=f'doc{index}',code_dependencies=item['code_dependencies'])
        else:binding.update(native_document_id=f'doc{index}',dataset_id='native-workspace',
            component_paths=item['native_components'],indexing_status=[{'indexing_status':'completed'}])
        if binding_invalid and index==0:binding['source_verification_sha256']='0'*64
        bindings.append(binding)
    tasks=[item['filename'][:-4].upper() for item in source['sources']]
    ident=app+'-r1-OLD-'+state
    feature={'application_id':app,'state_id':state,'feature_block_id':ident,
             'task_ids':tasks,'release_episode':episode,'observations':[]}
    for repeat in range(3):
        for index,task in enumerate(tasks):
            request=f'{app}-{repeat}-{task}';native_path=tmp_path/'native'/(request+'.json')
            # Deliberately associate tasks with another actual uploaded source.
            # No expected-source/task category mapping is available to impact.
            native_id=f'doc{(index+repeat+2)%8}'
            if app=='openwebui':
                response={'sources':[{'document':['synthetic returned source text'],
                                      'metadata':[{'file_id':native_id}]}]}
            else:response={'metadata':{'retriever_resources':[{
                'document_id':native_id,'dataset_id':'native-workspace','content':'synthetic returned source text'}]}}
            native={'request_id':request,'task_id':task,'state_id':state,'workspace_id':'native-workspace',
                'application_id':app,'native_response':response,'source_bindings':deepcopy(bindings),
                'answer':'synthetic answer never read by impact','completed':True,'valid_native_response':True,
                'native_configuration_receipt_path':str(config),'native_configuration_receipt_sha256':impact.sha(config),**SCOPE}
            write(native_path,native)
            output={**native,'receipt_path':str(native_path),'receipt_sha256':impact.sha(native_path)}
            metadata={'request_id':request,'task_id':task,'state_id':state,'trajectory_id':ident,
                      'episode_index':episode,'application_id':app,'phase':'profile',**SCOPE}
            joined={**metadata,'native_output':output,'root_meter_receipt':{
                'allocation_id':request,'native_query_units_reserved':1,'dispatch_safe_to_continue':True,
                'provider_join':{'joined':True},'native_reservation':{'request_id':request,'metadata':metadata}}}
            joined_path=tmp_path/'joined'/(request+'.json');write(joined_path,joined)
            feature['observations'].append({'task_id':task,'request_id':request,'state_id':state,
                'workspace_id':'native-workspace','feature_block_id':ident,'origin':'paid_old_native_contexts',
                'native_receipt_path':str(native_path),'root_joined_receipt_path':str(joined_path),
                'root_joined_receipt_sha256':impact.sha(joined_path),'returned_contexts':impact._contexts(native)})
    changes=[next(iter(sorted(model['dependencies'])))]
    return feature,bindings,changes,episode

def update_join(feature,index,mutate):
    observation=feature['observations'][index];path=Path(observation['root_joined_receipt_path'])
    value=impact.read(path);mutate(value);write(path,value)
    observation['root_joined_receipt_sha256']=impact.sha(path)

def update_native_and_join(feature,index,mutate):
    observation=feature['observations'][index];path=Path(observation['native_receipt_path'])
    native=impact.read(path);mutate(native);write(path,native)
    joined_path=Path(observation['root_joined_receipt_path']);joined=impact.read(joined_path)
    joined['native_output']={**native,'receipt_path':str(path),'receipt_sha256':impact.sha(path)}
    write(joined_path,joined);observation['root_joined_receipt_sha256']=impact.sha(joined_path)
    observation['returned_contexts']=impact._contexts(native)

@pytest.mark.parametrize('app',['dify','openwebui'])
@pytest.mark.parametrize('state',['HEALTHY','A_BAD'])
def test_actual_module_granularity_authenticates_and_admits_all8(tmp_path,app,state):
    feature,bindings,changes,episode=fixture(tmp_path,app,state)
    result=impact.build_impact(feature,bindings,changes,episode,evidence_dir=tmp_path/'proof')
    assert result['provenance_verified'] is True
    assert result['admitted_task_ids']==feature['task_ids']
    admitted,reason=policy.checked_impact(result,feature['task_ids'],changes,feature['feature_block_id'],episode)
    assert admitted==feature['task_ids'] and reason=='impact_admits_entire_catalog'
    proof=impact.read(next((tmp_path/'proof').glob('*.json')))
    assert proof['global_fallback'] is False and len(proof['native_receipts'])==24
    assert proof['answers_contracts_expected_source_hints_or_component_outcome_groups_used'] is False

def test_judgments_gold_and_wrong_logical_state_are_rejected(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    poisoned=deepcopy(feature);poisoned['primary_pass']=True
    with pytest.raises(ValueError,match='predecision'):impact.build_impact(poisoned,bindings,changes,episode)
    poisoned=deepcopy(feature);poisoned['observations'][0]['accepted_values']=['GOLD']
    with pytest.raises(ValueError,match='judgment'):impact.build_impact(poisoned,bindings,changes,episode)
    with pytest.raises(ValueError,match='logical OLD'):impact.build_impact(feature,bindings,changes,2)

def test_only_three_distinct_physically_paid_old_observations_enter(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    missing=deepcopy(feature);missing['observations'].pop()
    with pytest.raises(ValueError,match='Three separately'):impact.build_impact(missing,bindings,changes,episode)
    duplicate=deepcopy(feature);duplicate['observations'][-1]=deepcopy(duplicate['observations'][0])
    with pytest.raises(ValueError,match='Duplicate'):impact.build_impact(duplicate,bindings,changes,episode)

@pytest.mark.parametrize('fault',['zero_units','not_joined','future_scope','foreign_request'])
def test_root_native_scope_and_paid_join_are_authenticated(tmp_path,fault):
    feature,bindings,changes,episode=fixture(tmp_path)
    def mutate(value):
        if fault=='zero_units':value['root_meter_receipt']['native_query_units_reserved']=0
        elif fault=='not_joined':value['root_meter_receipt']['provider_join']['joined']=False
        elif fault=='future_scope':value['cohort_id']='development'
        else:value['root_meter_receipt']['native_reservation']['metadata']['request_id']='foreign'
    update_join(feature,0,mutate)
    with pytest.raises(ValueError):impact.build_impact(feature,bindings,changes,episode)

def test_changed_native_payload_cannot_use_old_join(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    path=Path(feature['observations'][0]['native_receipt_path']);value=impact.read(path)
    value['native_response']['metadata']['retriever_resources'][0]['document_id']='foreign';write(path,value)
    with pytest.raises(ValueError,match='changed or foreign'):impact.build_impact(feature,bindings,changes,episode)

def test_bad_binding_provenance_falls_back_conservatively(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path,binding_invalid=True)
    result=impact.build_impact(feature,bindings,changes,episode,evidence_dir=tmp_path/'proof')
    assert result['provenance_verified'] is False and result['admitted_task_ids']==feature['task_ids']
    assert impact.read(next((tmp_path/'proof').glob('*.json')))['global_fallback'] is True

def test_unsupported_changed_module_falls_back_without_fabricated_precision(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    result=impact.build_impact(feature,bindings,['code:unobserved/module.py'],episode,evidence_dir=tmp_path/'proof')
    assert result['admitted_task_ids']==feature['task_ids']
    assert impact.read(next((tmp_path/'proof').glob('*.json')))['global_fallback'] is True

def test_impact_does_not_open_contracts_questions_or_component_gold(tmp_path,monkeypatch):
    feature,bindings,changes,episode=fixture(tmp_path)
    original=impact.read;opened=[]
    def read_guard(path):
        path=Path(path);opened.append(path.name)
        assert path.name not in {'contracts.json','tasks.json','qualification.json','COMPONENT_PREFLIGHT.json'}
        return original(path)
    monkeypatch.setattr(impact,'read',read_guard)
    result=impact.build_impact(feature,bindings,changes,episode)
    assert result['provenance_verified'] is True
    assert 'source_manifest.json' in opened

def test_feature_and_saved_impact_receipts_are_immutable(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    receipt=tmp_path/'feature.json';write(receipt,feature)
    feature={**feature,'receipt_path':str(receipt),'receipt_sha256':impact.sha(receipt)}
    first=impact.build_impact(feature,bindings,changes,episode,evidence_dir=tmp_path/'proof')
    second=impact.build_impact(feature,bindings,changes,episode,evidence_dir=tmp_path/'proof')
    assert first==second
    changed=deepcopy(feature);changed['task_ids']=list(reversed(feature['task_ids']))
    with pytest.raises(ValueError,match='projection'):impact.build_impact(changed,bindings,changes,episode)

def test_future_profile_release_or_root_episode_cannot_be_relabelled_old(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    changed=deepcopy(feature);changed['release_episode']=3
    with pytest.raises(ValueError,match='release barrier'):impact.build_impact(changed,bindings,changes,episode)
    update_join(feature,0,lambda row:row.update(episode_index=3))
    with pytest.raises(ValueError,match='foreign'):impact.build_impact(feature,bindings,changes,episode)

def test_unknown_actual_returned_doc_stays_admitted_without_filename_guess(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    update_native_and_join(feature,0,lambda native:native['native_response']['metadata']['retriever_resources'][0].update(document_id='unknown-doc'))
    result=impact.build_impact(feature,bindings,changes,episode,evidence_dir=tmp_path/'proof')
    assert result['admitted_task_ids']==feature['task_ids']
    assert feature['task_ids'][0] in impact.read(next((tmp_path/'proof').glob('*.json')))['unknown_tasks']

def test_answer_changes_do_not_change_admission_or_source_verification(tmp_path):
    feature,bindings,changes,episode=fixture(tmp_path)
    before=impact.build_impact(feature,bindings,changes,episode)
    update_native_and_join(feature,0,lambda native:native.update(answer='a different generated judgment'))
    after=impact.build_impact(feature,bindings,changes,episode)
    assert before['admitted_task_ids']==after['admitted_task_ids']
    assert before['provenance_verified']==after['provenance_verified']

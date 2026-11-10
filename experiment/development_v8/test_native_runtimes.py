"""Offline guards, native scope isolation and state preparation; no services."""
from pathlib import Path
from unittest.mock import Mock
import hashlib
import json
import time
import pytest

from experiment.development_v8 import runtime_common as common
from experiment.development_v8.dify_runtime import NativeRuntime as Dify, RuntimeIncident
from experiment.development_v8.openwebui_runtime import NativeRuntime as OpenWebUI

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')

def config(tmp_path,monkeypatch,*,prompt='P0',receipt='receipt0'):
    monkeypatch.setattr(common,'ROOT',tmp_path)
    cohort=tmp_path/'cohort';cohort.mkdir(exist_ok=True)
    write(cohort/'tasks.json',{'tasks':[{'id':f'T{i}','question':f'Find record{i}','data_version':'v1'} for i in range(8)]})
    write(cohort/'source_manifest.json',{'sources':[],'documents':[]})
    guide=tmp_path/'experiment/validation_v7/GUIDANCE_FREEZE.json';write(guide,{'synthetic':True})
    freeze=tmp_path/('freeze'+prompt+'.json')
    write(freeze,{'files_sha256':{str(path):common.sha(path) for path in cohort.glob('*.json')},
        'prompt_id':prompt,'prompt_sha256':common.text_sha('Generic source lookup'),'cohort':'development'})
    auth=tmp_path/'auth.json';provider=tmp_path/'provider'
    write(auth,{'allow_native_dify':True,'allow_native_openwebui':True,'provider_phase':'EXTERNAL_V8',
        'expires_at_epoch':time.time()+600,'run_root':str(tmp_path),'provider_state_dir':str(provider),
        'guidance_freeze_sha256':common.sha(guide)})
    write(provider/'ACTIVE_ALLOCATION.json',{'allocation_id':'allocated','phase':'EXTERNAL_V8','expires_at_epoch':time.time()+600})
    return {'allow_native':True,'runtime_authorization_file':str(auth),'cohort_dir':str(cohort),
        'cohort_id':'development','prompt_id':prompt,'prompt_text':'Generic source lookup',
        'input_freeze_file':str(freeze),'input_freeze_sha256':common.sha(freeze),'receipt_scope':receipt,
        'scope_id':'development-'+prompt,'allow_new_dataset_scope':True}

@pytest.mark.parametrize('kind',[Dify,OpenWebUI])
def test_constructor_creates_no_resources(tmp_path,monkeypatch,kind):
    cfg=config(tmp_path,monkeypatch);run=tmp_path/'new-runtime'
    runtime=kind(cfg,run,'synthetic')
    assert not run.exists() and runtime.prepared_states==set()

@pytest.mark.parametrize('kind',[Dify,OpenWebUI])
def test_current_input_prompt_and_allocation_guards(tmp_path,monkeypatch,kind):
    cfg=config(tmp_path,monkeypatch);runtime=kind(cfg,tmp_path/'runtime','synthetic')
    runtime.set_allocation_id('allocated');runtime.set_operation_timeout(30)
    assert runtime._authorize()['provider_phase']=='EXTERNAL_V8'
    runtime.prompt_text='Changed after freeze'
    with pytest.raises(RuntimeError,match='cohort/prompt'):runtime._authorize()
    runtime.prompt_text=cfg['prompt_text'];runtime.set_allocation_id('wrong')
    with pytest.raises(RuntimeError,match='allocation'):runtime._authorize()

def test_input_bytes_cannot_change_between_callbacks(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic')
    runtime.set_allocation_id('allocated');runtime.set_operation_timeout(30)
    write(Path(cfg['cohort_dir'])/'tasks.json',{'tasks':[]})
    with pytest.raises(RuntimeError,match='input bytes'):runtime._authorize()

def test_scope_transition_archives_original_pointers_and_preserves_native_datasets(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic')
    runtime._authorize=Mock(return_value={})
    old={'owner':runtime.owner,'active_scope':{'scope_id':'old'},'used_dataset_scope_ids':['old'],
        'states':{'HEALTHY':{'indexed':True,'dataset_id':'old-data','app_id':'old-app','app_token':'private-key',
            'bindings':[{'native_id':'old-document'}],'configured':True,'source_metadata_dir':'unchanged'}},'containers':[]}
    write(runtime.platform_path,old);result=runtime.prepare_scope();new=common.read(runtime.platform_path)
    archives=list((runtime.private/'scope_archive').glob('*.json'))
    assert len(archives)==1 and common.read(archives[0])==old
    assert result['earlier_datasets_apps_indexes_or_receipts_removed'] is False
    assert new['states']['HEALTHY']['indexed'] is False
    assert new['states']['HEALTHY']['configured'] is True
    assert 'dataset_id' not in new['states']['HEALTHY'] and old['states']['HEALTHY']['dataset_id']=='old-data'
    assert new['used_dataset_scope_ids']==['old','development-P0']

def test_same_scope_reuses_fixed_index_and_new_receipt_namespace(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic');runtime._authorize=Mock()
    state={'indexed':True,'dataset_id':'same-data','app_id':'same-app'}
    old={'owner':runtime.owner,'active_scope':runtime._scope_definition(),'states':{'HEALTHY':state},
        'used_dataset_scope_ids':[runtime.scope_id],'containers':[]}
    write(runtime.platform_path,old);before=common.sha(runtime.platform_path)
    result=runtime.prepare_scope()
    assert result['fresh_native_dataset_app_admission_required'] is False and common.sha(runtime.platform_path)==before
    with pytest.raises(RuntimeIncident,match='already initialized'):runtime.prepare_scope()

def test_restore_continues_global_http_counter_without_native_calls(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic')
    write(runtime.platform_path,{'owner':runtime.owner,'states':{}})
    write(runtime.private/'http/HEALTHY/000003.json',{});write(runtime.private/'http/A_BAD/000008.json',{})
    assert runtime.restore_metadata()['http_receipt_counter_restored']==8
    write(runtime.private/'http/B_BAD/000008.json',{})
    with pytest.raises(RuntimeIncident,match='Duplicate'):runtime.restore_metadata()

def test_dify_query_cannot_lazy_start_unprepared_state(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic');runtime._authorize=Mock()
    runtime._assert_scope=Mock(return_value={'states':{'HEALTHY':{'indexed':True}}})
    runtime._request=Mock()
    with pytest.raises(RuntimeIncident,match='preparation'):runtime.query('HEALTHY','T0','query0')
    runtime._request.assert_not_called();assert not runtime.public.exists()

def test_dify_fresh_query_preserves_native_context_and_cohort_binding(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic');runtime._authorize=Mock()
    setup=runtime.public/'HEALTHY_SETUP.json';write(setup,{'prompt':'Generic source lookup'})
    binding={'native_id':'doc1','logical_id':'source.txt'}
    state={'indexed':True,'dataset_scope_id':runtime.scope_id,'dataset_id':'dataset1','app_token':'synthetic',
        'setup_receipt_path':str(setup),'bindings':[binding]}
    runtime._assert_scope=Mock(return_value={'states':{'HEALTHY':state}});runtime.prepared_states={'HEALTHY'}
    response={'answer':'original answer','conversation_id':'fresh1','metadata':{'retriever_resources':[{'document_id':'doc1','content':'original context'}]}}
    runtime._request=Mock(return_value=(response,{'http_status':200}))
    value=runtime.query('HEALTHY','T0','query0')
    assert value['native_response']==response and value['cohort']=='development' and value['prompt_id']=='P0'
    assert value['sources'][0]['logical_source_id']=='source.txt' and value['application_id']=='dify'
    assert runtime._request.call_args.kwargs['body']['conversation_id']==''
    with pytest.raises(FileExistsError):runtime.query('HEALTHY','T0','query0')
    assert runtime._request.call_count==1

def test_dify_preparation_stops_unwanted_before_starting_and_limits_two(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=Dify(cfg,tmp_path/'runtime','synthetic');runtime._authorize=Mock()
    runtime._platform=Mock(return_value={'states':{state:{'api':{'id':state}} for state in ('HEALTHY','A_BAD','B_BAD')}})
    runtime._owned=Mock(side_effect=lambda ident:{'Id':ident,'State':{'Running':ident!='HEALTHY'}})
    runtime._docker=Mock();runtime._wait_http=Mock()
    result=runtime.prepare_states(['HEALTHY','A_BAD'])
    assert runtime._docker.call_args_list[0].args==('stop','-t','3','B_BAD')
    assert runtime._docker.call_args_list[1].args==('start','HEALTHY')
    assert result['max_resident_native_API_states']==2
    with pytest.raises(RuntimeIncident):runtime.prepare_states(['HEALTHY','A_BAD','B_BAD'])

def test_openwebui_query_preserves_actual_file_contexts_and_cohort(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=OpenWebUI(cfg,tmp_path/'runtime','synthetic');runtime._authorize=Mock()
    runtime._remaining=Mock(return_value=30);runtime.prepared_states={'HEALTHY'}
    client=Mock();response={'answer':'native answer','completed':True,'request_id':'q0','native_response':{'unchanged':'payload'},
        'returned_sources':[{'document':['native bytes'],'metadata':[{'file_id':'f1'}]}]}
    client.chat.return_value=response
    runtime.states={'HEALTHY':{'client':client,'workspace_id':'k1','bindings':[{'native_file_id':'f1','logical_id':'source.txt','version':'v1'}]}}
    write(runtime.run/'source/HEALTHY/NATIVE_CONFIG.json',{'generic_prompt':'actual'})
    result=runtime.query('HEALTHY','T0','q0')
    assert result['native_response']==response['native_response'] and result['sources'][0]['logical_source_id']=='source.txt'
    assert result['cohort']=='development' and result['prompt_id']=='P0'
    with pytest.raises(FileExistsError):runtime.query('HEALTHY','T0','q0')
    assert client.chat.call_count==1

def test_openwebui_template_and_native_topk_are_prospective(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=OpenWebUI(cfg,tmp_path/'runtime','synthetic')
    private=tmp_path/'private';private.mkdir();env,password,template=runtime._env(private)
    assert template.count('{{CONTEXT}}')==1 and cfg['prompt_text'] in template
    assert 'RAG_TOP_K=8\n' in env.read_text(encoding='utf-8')
    assert password and 'expected_answer' not in template

def test_openwebui_preparation_parks_before_starts(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);runtime=OpenWebUI(cfg,tmp_path/'runtime','synthetic');runtime._authorize=Mock()
    runtime.states={state:{'container_id':state,'label':state,'url':'http://127.0.0.1'} for state in ('HEALTHY','A_BAD','B_BAD')}
    events=[]
    def docker(*args,**kwargs):
        if args[0]=='inspect':return json.dumps([{'Config':{'Labels':{'tosem.owner':args[1]}},'State':{'Running':args[1]!='HEALTHY'}}])
        events.append(args);return ''
    runtime._docker=Mock(side_effect=docker);runtime._wait_ready=Mock()
    result=runtime.prepare_states(['HEALTHY','A_BAD'])
    assert events==[('stop','--time','3','B_BAD'),('start','HEALTHY')]
    assert result['prepared_states']==['HEALTHY','A_BAD']

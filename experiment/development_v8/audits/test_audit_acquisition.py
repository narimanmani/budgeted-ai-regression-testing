"""Pure malformed-evidence checks; no real experiment data or native calls."""
from copy import deepcopy
import json
import pytest
from experiment.development_v8.audits.audit_acquisition import (
    choose_provider_events, prompt_context, model_check, join_check,
)

def event():
    return {'request_id':'keep','allocation_id':'allocation','path':'/v1/chat/completions',
        'backend_receipt_sha256':'backend','http_status':200,'upstream_http_status':200,
        'llamacpp_response_validation_passed':True,'bridge_input_truncation':False,
        'upstream_request':{'model':'tosem-qwen2.5-7b-q4','temperature':0,'max_tokens':96,'cache_prompt':False,
            'messages':[{'role':'system','content':'<context>\nOriginal source\n</context>'}]},
        'upstream_actual_response':{'__verbose':{'generation_settings':{'temperature':0,'n_predict':96},'truncated':False},
            'timings':{'cache_n':0},'usage':{'prompt_tokens':50,'completion_tokens':3,'prompt_tokens_details':{'cached_tokens':0}}},
        'generate_gpu_allocation_seconds_including_failure':2.5}

def test_provider_filter_does_not_parse_unrelated_acquisition_outputs(tmp_path):
    path=tmp_path/'log.jsonl'
    path.write_text(json.dumps(event())+'\n'+str('{"request_id":"other", this is deliberately not JSON')+'\n',encoding='utf-8')
    assert choose_provider_events(path,{'keep'})['keep']['allocation_id']=='allocation'

def test_provider_missing_or_duplicated_named_receipt_fails(tmp_path):
    path=tmp_path/'log.jsonl';path.write_text(json.dumps(event())+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='missing'):choose_provider_events(path,{'missing'})
    path.write_text((json.dumps(event())+'\n')*2,encoding='utf-8')
    with pytest.raises(ValueError,match='Duplicate'):choose_provider_events(path,{'keep'})

def test_context_matches_actual_native_returned_content():
    value=event()
    assert prompt_context('dify',value,{'returned_contexts':[{'content':'Original source'}]})=='\nOriginal source\n'
    assert prompt_context('openwebui',value,{'returned_contexts':[{'document':'Original source'}]})=='\nOriginal source\n'
    with pytest.raises(ValueError):prompt_context('dify',value,{'returned_contexts':[{'content':'Invented source'}]})
    with pytest.raises(ValueError):prompt_context('openwebui',value,{'returned_contexts':[{'document':'Invented source'}]})

def test_ambiguous_or_missing_context_expansion_fails():
    value=event();value['upstream_request']['messages'][0]['content']='No context in actual request'
    with pytest.raises(ValueError):prompt_context('dify',value,{'returned_contexts':[]})
    value['upstream_request']['messages'][0]['content']='<context>one</context><context>two</context>'
    with pytest.raises(ValueError):prompt_context('dify',value,{'returned_contexts':[]})

def test_model_limit_cache_and_provenance_mutations_fail():
    assert model_check(event(),'backend')['completion_tokens']==3
    for location,key,new in [('upstream_request','temperature',0.5),('upstream_request','max_tokens',128),
        ('upstream_request','cache_prompt',True),('','backend_receipt_sha256','wrong'),('','bridge_input_truncation',True)]:
        value=event();target=value[location] if location else value;target[key]=new
        with pytest.raises(ValueError):model_check(value,'backend')
    value=event();value['upstream_actual_response']['timings']['cache_n']=10
    with pytest.raises(ValueError):model_check(value,'backend')

def test_join_requires_exact_allocation_counts_and_actual_cost():
    value=event();receipt={'allocation_id':'allocation','dispatch_safe_to_continue':True,
        'provider_join':{'joined':True,'provider_request_ids':['keep'],'chat_boundary_attempts':1,
            'embedding_boundary_attempts':0,'gpu_allocation_seconds':2.5,'embedding_cpu_seconds_recorded':0}}
    chat,embedding=join_check(receipt,{'keep':value});assert len(chat)==1 and not embedding
    for key,new in [('chat_boundary_attempts',2),('gpu_allocation_seconds',0),('joined',False)]:
        bad=deepcopy(receipt);bad['provider_join'][key]=new
        with pytest.raises(ValueError):join_check(bad,{'keep':value})
    value['allocation_id']='other'
    with pytest.raises(ValueError):join_check(receipt,{'keep':value})

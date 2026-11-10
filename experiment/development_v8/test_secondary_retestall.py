"""Offline scope, non-reuse, accounting and saved-judgment diagnostic tests."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from experiment.development_v8.secondary_retestall import (
    PHASE, ORDER, EPISODES, DiagnosticCampaign, planned_pairs, pair_record,
    require_closed_primary, require_reused_dify_scope, evaluate_saved, read, sha,
)
from experiment.validation_v7.execution.source_channels import CanonicalContracts


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8'); return path


def test_exact_all_task_transition_frame_has_48_fresh_slots():
    tasks = ['Q'+str(i) for i in range(8)]; pairs = planned_pairs(tasks)
    assert len(pairs) == 24 and [(p['old_state'], p['new_state']) for p in pairs[::8]] == [(a,b) for _,a,b in EPISODES]
    assert all([p['task_id'] for p in pairs if p['episode_index']==e] == tasks for e in (1,2,3))
    with pytest.raises(ValueError, match='eight'): planned_pairs(tasks[:-1]+tasks[:1])


def test_no_diagnostic_before_every_original_primary_driver_and_episode_closes(tmp_path):
    rows = []
    for app, rep in ORDER:
        path = tmp_path/f'main-{app}-r{rep}'; rows.append({'application_id':app,'repetition':rep,'output_dir':str(path)})
        save(path/'DRIVER_COMPLETION.json', {'success': True, 'error': None, 'application_id':app,'repetition':rep})
        ids = ['T'+str(i) for i in range(20)]
        save(path/'block/BLOCK_COMPLETION.json', {'application_id':app,'repetition':rep,'error':None,
            'planned_trajectories':20,'completed_trajectories':20,'logical_episode_closures':{str(e):ids for e in (1,2,3)}})
    assert len(require_closed_primary(tmp_path, {'main_block_order':rows})) == 8
    save(tmp_path/'main-dify-r2/DRIVER_COMPLETION.json', {'success':False,'error':'incomplete'})
    with pytest.raises(ValueError, match='four original'): require_closed_primary(tmp_path, {'main_block_order':rows})


def test_reserved_full_native_lifetime_stops_before_unaffordable_dispatch_and_preserves_receipt():
    class Campaign:
        auth={'max_native_timeout_seconds':600,'phase_gpu_cap_seconds':30000,'shared_gpu_cap_seconds':43200,'prior_shared_gpu_seconds':9316}
        current=1000.; calls=0
        def health(self): return {'counters':{'gpu_allocation_seconds_accounted':self.current}}
        def query(self,*args): self.calls+=1;return {'answer':'same'},{'canonical':True}
    c=Campaign();wrapped=DiagnosticCampaign(c,{'gpu_allocation_seconds':1000.},{'generation_allocation_ceiling_seconds':2400,'native_lifetime_admission_reserve_seconds':600})
    result=wrapped.query('fresh',{'phase':PHASE},None)
    assert result[1] == {'canonical':True} and c.calls==1
    c.current=2801.
    with pytest.raises(ValueError,match='full native lifetime'):wrapped.query('other',{'phase':PHASE},None)
    assert c.calls==1
    with pytest.raises(ValueError):wrapped.query('profile',{'phase':'profile'},None)


def specimen(tmp_path):
    block=tmp_path/'secondary';scope={'cohort_id':'validation','prompt_candidate_id':'P0',
        'prompt_text_sha256':'p'*64,'input_freeze_sha256':'f'*64}
    tasks=['Q'+str(i) for i in range(8)]; spec={'contracts':[{'id':task,'data_version':'v1',
        'accepted_values':['ALPHA'],'required_logical_source_id':task,'required_source_version':'v1'} for task in tasks]}
    contract_path=save(tmp_path/'contracts.json',spec); contracts=CanonicalContracts(spec)
    owner='app-secondary-retestall-r1'; records={};counter=0
    class FakeMeter:
        def query(self,state,task,phase,trajectory,episode):
            nonlocal counter
            counter+=1;ident='FRESH-'+str(counter)
            binding={'native_id':task,'logical_source_id':task,'version':'v1','workspace_id':state,'state_id':state}
            output={'answer':'ALPHA' if state=='HEALTHY' else 'UNKNOWN','completed':True,'valid_native_response':True,
                'request_id':ident,'state_id':state,'task_id':task,'workspace_id':state,**scope,
                'source_bindings':[binding],'native_response':{'sources':[{'id':task}]}}
            metadata={'application_id':'app','repetition':1,'request_id':ident,'phase':phase,'state_id':state,
                'task_id':task,'episode_index':episode,'trajectory_id':trajectory,**scope}
            receipt={'native_query_units_reserved':1,'dispatch_safe_to_continue':True,
                'native_reservation':{'metadata':metadata},'receipt_path':str(tmp_path/'sealed'/(ident+'.json'))}
            save(receipt['receipt_path'],receipt)
            row={**metadata,'native_output':output,'root_meter_receipt':receipt}
            raw_path=save(block/'meter/raw'/(ident+'.json'),row)
            records[ident]=raw_path
            return {**row,'receipt_path':str(raw_path),'receipt_sha256':sha(raw_path)}
    pointers=[];meter=FakeMeter()
    for item in planned_pairs(tasks):
        pair=pair_record(meter,contracts,item,owner)
        path=save(block/'pairs'/f'E{item["episode_index"]}-{item["task_id"]}.json',pair)
        pointers.append({'path':str(path),'sha256':sha(path)})
    save(block/'DISPATCH_PLAN.json',{'phase':PHASE,'trajectory_id':owner,'task_ids':tasks,'pairs':planned_pairs(tasks),
        'scope':scope,'contracts_file':str(contract_path),'contracts_sha256':sha(contract_path)})
    completion={'application_id':'app','repetition':1,'complete':True,'error':None,'native_queries':48,
        'completed_pairs':24,'pair_files':pointers}
    save(block/'SECONDARY_COMPLETION.json',completion)
    return block,records


def update_pair_pointer(block,index,pair):
    completion=read(block/'SECONDARY_COMPLETION.json');ptr=completion['pair_files'][index]
    path=save(ptr['path'],pair);ptr['sha256']=sha(path);save(block/'SECONDARY_COMPLETION.json',completion)


def test_saved_evaluation_reconstructs_all24_contract_pairs_without_reference_or_native(tmp_path):
    block,records=specimen(tmp_path);opened=[]
    def limited_read(path):
        opened.append(str(path));return read(path)
    result=evaluate_saved(block,read_json=limited_read)
    assert result['passed'] and result['unique_native_queries']==48 and len(result['pairs'])==24
    assert sum(p['unrestricted_alarm'] for p in result['pairs'])==16
    assert not result['counts_toward_primary_80'] and not result['K_budget_matched']
    assert not any('/reference' in path or '/profile' in path or 'history' in path for path in opened)


def test_partial_diagnostic_rejected_before_raw_answers_read(tmp_path):
    block,records=specimen(tmp_path);complete=read(block/'SECONDARY_COMPLETION.json');complete['complete']=False
    save(block/'SECONDARY_COMPLETION.json',complete);opened=[]
    def limited_read(path): opened.append(str(path));return read(path)
    with pytest.raises(ValueError,match='Complete fixed'):evaluate_saved(block,read_json=limited_read)
    assert len(opened)==1


def test_reused_raw_execution_and_changed_judgments_cannot_be_masked_by_new_pair_hash(tmp_path):
    block,records=specimen(tmp_path);complete=read(block/'SECONDARY_COMPLETION.json');pair=read(complete['pair_files'][0]['path'])
    pair['new']=deepcopy(pair['old']);update_pair_pointer(block,0,pair)
    with pytest.raises(ValueError,match='identity mismatch or reused'):evaluate_saved(block)
    block2,records2=specimen(tmp_path/'second');complete=read(block2/'SECONDARY_COMPLETION.json');pair=read(complete['pair_files'][0]['path'])
    pair['old']['check']['primary_pass']=False;update_pair_pointer(block2,0,pair)
    with pytest.raises(ValueError,match='unchanged checker'):evaluate_saved(block2)


def test_unknown_postseal_root_receipt_addition_fails_even_with_rehashed_raw(tmp_path):
    block,records=specimen(tmp_path);complete=read(block/'SECONDARY_COMPLETION.json');pair=read(complete['pair_files'][0]['path'])
    path=Path(pair['old']['receipt_path']);raw=read(path);raw['root_meter_receipt']['unregistered_addition']=True;save(path,raw)
    pair['old']['receipt_sha256']=sha(path);update_pair_pointer(block,0,pair)
    with pytest.raises(ValueError,match='Canonical root receipt'):evaluate_saved(block)


def test_dify_missing_index_cannot_trigger_replacement_probe_or_reindex():
    class Runtime:
        platform={'active_scope':{'scope':'validation-P2'},'states':{s:{'configured':True,'indexed':True} for s in ('HEALTHY','A_BAD','B_BAD')}}
        def _platform(self): return self.platform
        def _scope_definition(self): return {'scope':'validation-P2'}
    runtime=Runtime();require_reused_dify_scope(runtime)
    runtime.platform=deepcopy(runtime.platform);runtime.platform['states']['B_BAD']['indexed']=False
    with pytest.raises(ValueError,match='no diagnostic provider probes'):require_reused_dify_scope(runtime)


def test_full_driver_offline_uses48_fresh_queries_without_profiles_history_or_reference(tmp_path,monkeypatch):
    import types
    from experiment.development_v8 import secondary_retestall as secondary, control
    from experiment.validation_v7.execution import runner
    run=tmp_path/'run';run.mkdir();registration=save(run/'SECONDARY_RETESTALL_REGISTRATION.json',{'test_only':True})
    tasks=['Q'+str(i) for i in range(8)];cohort=run/'cohort';scope={'cohort_id':'validation','prompt_candidate_id':'P0',
        'prompt_text_sha256':'p'*64,'input_freeze_sha256':'f'*64}
    document={'contracts':[{'id':task,'data_version':'v1','accepted_values':['ALPHA'],
        'required_logical_source_id':task,'required_source_version':'v1'} for task in tasks]}
    save(cohort/'contracts.json',document);freeze=save(run/'VALIDATION_FREEZE.json',{'test_only':True})
    save(run/'MAIN_BUDGET_MASTER.json',{'main_start_native_ledger_entries':403})
    for app,rep in ORDER:save(run/f'main-{app}-r{rep}'/'block/BLOCK_COMPLETION.json',{'physical_usage':{'native_query_units':568}})
    authority={'generation_allocation_ceiling_seconds':2400,'native_lifetime_admission_reserve_seconds':600,
        'attribution':{'added_after_primary_main_started':True,'counts_toward_primary_80':False}}
    ready={'registration':authority,'case':{'task_ids':tasks,'scope':scope,'contract_document':document,'cohort_dir':cohort},
        'output':run/'secondary-retestall-openwebui-r1','extra_files':[],'freeze':freeze,'index':0,
        'stage_path':run/'unused-stage','config':{}}
    monkeypatch.setattr(secondary,'validate_registration',lambda *args:ready)
    class Guard:
        implementation_sha256={}
        def __init__(self,**kwargs):pass
        def check(self):pass
    monkeypatch.setattr(runner,'FrozenGuidanceGuard',Guard)
    class Campaign:
        auth={'max_native_timeout_seconds':600,'phase_gpu_cap_seconds':30000,'shared_gpu_cap_seconds':43200,
              'prior_shared_gpu_seconds':9316,'prior_native_query_units':2071,'native_query_cap':2929}
        instances=[]
        def __init__(self,*args):self.entries=[None]*2675;self.requests=[];self.closed=False;self.__class__.instances.append(self)
        def _ledger(self):return self.entries,{},''
        def health(self):return {'counters':{'gpu_allocation_seconds_accounted':5000.+len(self.requests)}}
        def perform(self,ident,action,metadata=None):
            value=action(600);units=int(metadata is not None)
            receipt={'native_query_units_reserved':units,'dispatch_safe_to_continue':True,
                'native_reservation':{'metadata':metadata} if metadata else None,
                'provider_join':{'provider_chat_boundaries':units,'gpu_allocation_seconds':float(units)},
                'receipt_path':str(run/'sealed'/(ident+'.json'))}
            save(receipt['receipt_path'],receipt);return value,receipt
        def query(self,ident,metadata,action):
            assert ident not in self.requests and metadata['phase']==PHASE
            self.entries.append(metadata);self.requests.append(ident);return self.perform(ident,action,metadata)
        def perform_setup(self,ident,action):return self.perform(ident,action)
        def close(self):self.closed=True
    monkeypatch.setattr(control,'Campaign',Campaign)
    class Runtime:
        def __init__(self,*args):self.prepared=set();self.allocation_id=None
        def set_allocation_id(self,ident):self.allocation_id=ident
        def set_operation_timeout(self,timeout):pass
        def setup(self):return {'model_calls':0}
        def prepare_states(self,states):self.prepared=set(states);return {'model_calls':0}
        def source_bindings(self,state):return [{'native_id':task,'logical_source_id':task,'version':'v1','workspace_id':state,'state_id':state} for task in tasks]
        def query(self,state,task,ident):
            assert state in self.prepared
            return {'answer':'ALPHA' if state=='HEALTHY' else 'UNKNOWN','completed':True,'valid_native_response':True,
                'request_id':ident,'state_id':state,'task_id':task,'workspace_id':state,**scope,'native_response':{'sources':[{'id':task}]}}
        def cleanup(self):return {'owned_services_stopped':True}
    original_import=secondary.importlib.import_module
    monkeypatch.setattr(secondary.importlib,'import_module',lambda name:types.SimpleNamespace(NativeRuntime=Runtime)
        if name=='experiment.development_v8.openwebui_runtime' else original_import(name))
    result=secondary.run_block(run,registration,'openwebui',1)
    assert result['success'] and result['complete'] and result['native_queries']==result['planned_native_queries']==48
    assert result['physical_usage']['native_query_units']==48 and result['completed_pairs']==24
    assert Campaign.instances[0].closed and len(Campaign.instances[0].requests)==48
    assert all('-300' in ident and PHASE in ident for ident in Campaign.instances[0].requests)
    assert evaluate_saved(ready['output'])['passed']

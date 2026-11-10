"""Synthetic transport fixtures only; no application/model operation."""
import json
from pathlib import Path
import pytest
from experiment.development_v8.acquisition import MeteredApplication, acquire, SCOPE_FIELDS
from experiment.validation_v7.execution.runner import FrozenGuidanceGuard, StudyIncident
from experiment.validation_v7.execution.source_channels import CanonicalContracts

SCOPE={'cohort_id':'development','prompt_candidate_id':'P0','prompt_text_sha256':'a'*64,'input_freeze_sha256':'b'*64}
TASKS=[f'D{i:02}' for i in range(8)]

class Runtime:
    def __init__(self,bad_scope=False):self.calls=[];self.prepared=[];self.bad_scope=bad_scope;self.cleaned=False
    def set_allocation_id(self,value):self.ident=value
    def set_operation_timeout(self,value):self.timeout=value
    def setup(self):return {'synthetic_setup':True}
    def prepare_states(self,states):self.prepared.append(states);return {'synthetic_states':states}
    def source_bindings(self,state):return []
    def query(self,state,task,ident):
        self.calls.append((state,task,ident))
        return {'request_id':ident,'task_id':task,'state_id':state,'workspace_id':'synthetic',
                'completed':True,'answer':task,'valid_native_response':True,'sources':[],**SCOPE,
                **({'prompt_candidate_id':'WRONG'} if self.bad_scope else {})}
    def cleanup(self):self.cleaned=True;return {'synthetic_cleanup':True}

class Campaign:
    def __init__(self):self.metadata=[]
    def perform_setup(self,ident,operation):
        return operation(600),{'allocation_id':ident,'dispatch_safe_to_continue':True,'native_query_units_reserved':0,
            'provider_join':{'joined':True,'chat_boundary_attempts':0,'embedding_boundary_attempts':0,'gpu_allocation_seconds':0}}
    def query(self,ident,metadata,operation):
        self.metadata.append(metadata)
        return operation(600),{'allocation_id':ident,'dispatch_safe_to_continue':True,'native_query_units_reserved':1,
            'native_reservation':{'request_id':ident,'metadata':metadata},
            'provider_join':{'joined':True,'chat_boundary_attempts':1,'embedding_boundary_attempts':0,'gpu_allocation_seconds':0}}

class Guard:
    def check(self):pass

def fixture(tmp_path,bad_scope=False):
    runtime=Runtime(bad_scope);campaign=Campaign()
    meter=MeteredApplication(runtime,campaign,tmp_path/'meter','synthetic-app',100,SCOPE)
    contracts=CanonicalContracts({'contracts':[{'id':t,'data_version':'v1','accepted_values':[t]} for t in TASKS]})
    return runtime,campaign,meter,contracts

def test_development_complete48_and_scoped_prior_reservations(tmp_path):
    runtime,campaign,meter,contracts=fixture(tmp_path)
    result=acquire(meter,contracts,TASKS,phase='development',guard=Guard())
    assert result['outputs']==result['planned_outputs']==48
    assert result['physical_usage']['native_query_units']==48
    assert runtime.prepared==[['HEALTHY'],['A_BAD'],['B_BAD']] and runtime.cleaned
    assert all(all(row[k]==SCOPE[k] for k in SCOPE_FIELDS) for row in campaign.metadata)
    assert len({row['request_id'] for row in campaign.metadata})==48

def test_qualification_exact32_subset(tmp_path):
    runtime,campaign,meter,contracts=fixture(tmp_path)
    subsets={'A_BAD':TASKS[:2]+TASKS[4:6],'B_BAD':TASKS[2:6]}
    result=acquire(meter,contracts,TASKS,phase='qualification',guard=Guard(),selected_by_state=subsets)
    assert result['outputs']==32 and len(runtime.calls)==32

def test_scope_mismatch_retains_first_observation_then_stops(tmp_path):
    runtime,campaign,meter,contracts=fixture(tmp_path,True)
    with pytest.raises(StudyIncident,match='scope mismatch'):
        acquire(meter,contracts,TASKS,phase='development',guard=Guard())
    assert len(runtime.calls)==1 and runtime.cleaned
    assert len(list((meter.run_dir/'raw').glob('*.json')))==1
    assert json.loads((meter.run_dir/'REFERENCE_COMPLETION.json').read_text())['error'] is not None

def test_scope_must_be_explicit(tmp_path):
    with pytest.raises(ValueError,match='scope'):
        MeteredApplication(Runtime(),Campaign(),tmp_path/'x','x',1,{'cohort_id':'development'})

def test_task_universe_rejected_before_native_work(tmp_path):
    runtime,campaign,meter,contracts=fixture(tmp_path)
    with pytest.raises(ValueError,match='eight-task'):
        acquire(meter,contracts,TASKS[:-1],phase='development',guard=Guard())
    assert not runtime.calls and not campaign.metadata

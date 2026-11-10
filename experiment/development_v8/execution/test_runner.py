"""Offline software fixtures only; no observed application/model results."""
import json
from pathlib import Path
import pytest
from experiment.development_v8.execution.runner import (
    ALL_ARMS, BlockRunner, Contracts, FrozenGuidanceGuard, MeteredApplication, StudyIncident,
    profile_feature, sha, source_check, trajectory_plan,
)


SCOPE={'cohort_id':'validation','prompt_candidate_id':'P0','prompt_text_sha256':'a'*64,'input_freeze_sha256':'b'*64}

class Clock:
    def __init__(self): self.now=0.
    def __call__(self): return self.now
    def advance(self,value): self.now+=value


class Guard:
    def __init__(self): self.calls=0
    def check(self): self.calls+=1


class Runtime:
    def __init__(self,clock,late=False): self.clock=clock;self.calls=[];self.late=late;self.cleaned=False;self.prepared=set();self.preparations=[];self.start_transitions=0
    def set_allocation_id(self,ident): self.allocation=ident
    def set_operation_timeout(self,seconds): self.timeout=seconds
    def setup(self): self.clock.advance(1);return {'synthetic_software_fixture':True}
    def prepare_states(self,states):
        assert 1<=len(set(states))<=2
        self.preparations.append(tuple(states))
        if self.prepared!=set(states):
            self.start_transitions+=1;self.clock.advance(3.)
        else:self.clock.advance(.01)
        self.prepared=set(states)
        return {'synthetic_software_fixture':True,'prepared_states':list(states),'model_calls':0}
    def cleanup(self): self.cleaned=True;self.clock.advance(.1);return {'synthetic_software_fixture':True}
    def source_bindings(self,state):
        return [{'logical_id':f'{task}.txt','version':'v1','native_document_id':f'{state}-{task}',
                 'workspace_id':f'ws-{state}','state_id':state} for task in [f'q{i}' for i in range(8)]]
    def query(self,state,task,request):
        assert self.allocation==request and state in self.prepared
        self.calls.append((state,task,request))
        costs={'q0':.01,'q1':.30,'q2':.02,'q3':.03,'q4':.04,'q5':.09,'q6':.10,'q7':.11,'q8':.05,'q9':.06,'q10':.07,'q11':.08}
        self.clock.advance(costs[task])
        if self.late and '-comparison-' in request:
            self.clock.advance(100);self.late=False
        failed=(state=='A_BAD' and task=='q1') or (state=='B_BAD' and task=='q6')
        return {**SCOPE,'request_id':request,'task_id':task,'valid_native_response':True,'completed':True,'answer':'bad' if failed else 'good',
                'state_id':state,'workspace_id':f'ws-{state}',
                'native_response':{'sources':[{'id':'native-chunk','metadata':{'document_id':f'{state}-{task}'}}]},
                'source_bindings':self.source_bindings(state)}


class Campaign:
    def __init__(self): self.metadata=[];self.bad=False
    def query(self,ident,metadata,action):
        self.metadata.append(metadata);value=action(180)
        return value,{'dispatch_safe_to_continue':not self.bad,'native_query_units_reserved':1,
                      'allocation_id':ident,'native_reservation':{'request_id':ident,'metadata':metadata},
                      'provider_join':{'joined':True,'chat_boundary_attempts':1,'embedding_boundary_attempts':1,
                                       'gpu_allocation_seconds':.1,'embedding_cpu_seconds_recorded':.01}}
    def perform_setup(self,ident,action):
        return action(600),{'dispatch_safe_to_continue':True,'native_query_units_reserved':0,
            'provider_join':{'chat_boundary_attempts':0,'embedding_boundary_attempts':36,
                             'gpu_allocation_seconds':0.,'embedding_cpu_seconds_recorded':.5}}


def impact_builder(features,bindings,changes,episode):
    admitted=features['task_ids'] if changes==['code:a.py'] else ['q1','q2','q6','q7']
    return {'source':'paid_old_native_contexts','feature_block_id':features['feature_block_id'],
            'episode_index':episode,'predecision':True,'current_or_future_outcomes_used':False,
            'provenance_verified':True,'task_ids':features['task_ids'],'admitted_task_ids':admitted,
            'changed_tokens':changes,'evidence_receipt_sha256':'b'*64}


def fixture(tmp_path,late=False):
    clock=Clock();runtime=Runtime(clock,late);campaign=Campaign();guard=Guard()
    meter=MeteredApplication(runtime,campaign,tmp_path/'meter','software-fixture',1,scope=SCOPE,clock=clock)
    contracts=Contracts([{'id':f'q{i}','accepted_values':['good'],'required_logical_source_id':f'q{i}.txt',
                         'required_source_version':'v1'} for i in range(8)])
    allowances=[]
    def affordable(features,plan,phase):
        allowances.append(phase);return {'allowed':True,'synthetic_software_fixture':True}
    runner=BlockRunner(meter,contracts,list(contracts.specs),impact_builder,
        {1:['code:a.py'],2:['code:a.py'],3:['code:b.py']},tmp_path/'block',
        guard=guard,clock=clock,affordability_gate=affordable)
    return runner,meter,runtime,campaign,guard,allowances


def test_complete_block_enforces_release_own_history_and_common_features(tmp_path):
    runner,meter,runtime,campaign,guard,allowances=fixture(tmp_path)
    result=runner.run()
    assert result['completed_trajectories']==20 and result['physical_usage']['native_query_units']==568
    assert runtime.cleaned and guard.calls>=60
    assert allowances==['before_own_calibration','before_episode_1','before_episode_2','before_episode_3']
    profile=[x for x in campaign.metadata if x['phase']=='profile']
    assert len(profile)==48
    assert all(row['episode_index']==2 for row in profile if row['state']=='A_BAD')
    events=[json.loads(x) for x in (runner.run_dir/'events.jsonl').read_text().splitlines()]
    release=next(i for i,x in enumerate(events) if x['kind']=='old_feature_block_released' and x['state_id']=='A_BAD')
    assert len({x['trajectory_id'] for x in events[:release] if x['kind']=='episode_closed' and x['episode_index']==1})==20
    for trajectory in runner.trajectories.values():
        warm=trajectory['history_regime']=='WARM'
        assert len(trajectory['calibration_pairs'])==(8 if warm else 0)
        expected_comparison=12 if trajectory['budget_id']=='LOW' else 24
        assert trajectory['actual_own_physical_usage']['native_query_units']==expected_comparison+(16 if warm else 0)
        assert trajectory['allocated_shared_feature_usage']['native_query_units']==48
        assert all(x['trajectory_id']==trajectory['trajectory_id'] for x in trajectory['final_history'])
        assert all(x['timely'] for x in trajectory['selected_pairs'])
    for episode in (1,2,3):
        decisions=[t['decisions'][episode-1] for t in runner.trajectories.values()]
        assert len({x['feature_receipt_sha256'] for x in decisions})==1
    warm_guide=runner.trajectories['software-fixture-r1-LOW-WARM-CG1']
    warm_combined=runner.trajectories['software-fixture-r1-LOW-WARM-I1_H1']
    assert warm_guide['decisions'][2]['chosen_arm']=='I1_H0'
    assert [p['task_id'] for p in warm_guide['selected_pairs'] if p['episode_index']==3]==['q2','q6']
    assert [p['task_id'] for p in warm_combined['selected_pairs'] if p['episode_index']==3]==['q1','q2']
    assert any(p['primary_alarm_credited'] for p in warm_guide['selected_pairs'] if p['episode_index']==3)
    assert not any(p['primary_alarm_credited'] for p in warm_combined['selected_pairs'] if p['episode_index']==3)


def test_late_old_output_is_paid_but_new_and_history_credit_suppressed(tmp_path):
    runner,meter,runtime,campaign,guard,_=fixture(tmp_path,late=True)
    result=runner.run()
    first=runner.trajectories['software-fixture-r1-LOW-COLD-I0_H0']
    assert result['physical_usage']['native_query_units']==565
    assert not [x for x in first['selected_pairs'] if x['episode_index']==1]
    calls=[x for x in campaign.metadata if x['trajectory_id']==first['trajectory_id'] and x['episode_index']==1]
    assert len(calls)==1 and calls[0]['state']=='HEALTHY'
    assert first['episodes'][0]['deadline_overrun_seconds']>0
    assert not [x for x in first['final_history'] if x['episode_index']==1]


def test_early_A_profile_and_duplicate_runner_are_rejected(tmp_path):
    runner,*_=fixture(tmp_path)
    runner.started=0
    with pytest.raises(StudyIncident,match='ALL20'): runner._profile('A_BAD',2,trajectory_plan('software-fixture',1))
    runner.used=True
    with pytest.raises(StudyIncident,match='One-use'): runner.run()


def test_root_unsafe_receipt_retains_reserved_cost_and_stops(tmp_path):
    runner,meter,runtime,campaign,*_=fixture(tmp_path)
    campaign.bad=True
    meter.metadata_step('prepare-unsafe-test',lambda:runtime.prepare_states(['HEALTHY']))
    with pytest.raises(StudyIncident): meter.query('HEALTHY','q0','profile','feature',1)
    assert len(meter.query_records)==1
    assert meter.query_records[0]['root_meter_receipt']['native_query_units_reserved']==1


def test_full_order_is_mirrored_in_second_repetition():
    first=trajectory_plan('app',1);second=trajectory_plan('app',2)
    assert [(x['arm'],x['budget_id'],x['history_regime']) for x in first]==list(reversed(
        [(x['arm'],x['budget_id'],x['history_regime']) for x in second]))


def test_state_start_costs_are_common_paid_and_excluded_from_policy_episode_timer(tmp_path):
    runner,meter,runtime,*_=fixture(tmp_path)
    result=runner.run()
    assert runtime.start_transitions==2
    assert len(runtime.preparations)==6
    assert set(runtime.preparations[-1])=={'HEALTHY','B_BAD'}
    assert all(len(set(states))<=2 for states in runtime.preparations)
    preparation=[row for row in meter.operations if row.get('label','').startswith('main-prepare-')]
    assert len(preparation)==6 and all(row['root_meter_receipt']['native_query_units_reserved']==0 for row in preparation)
    setup_wall=sum(row['elapsed_seconds'] for row in meter.operations if row['phase']=='setup')
    assert setup_wall>=7
    for trajectory in runner.trajectories.values():
        assert trajectory['allocated_common_setup_wall_seconds']==setup_wall
        assert trajectory['own_comparison_wall_seconds']<setup_wall
    events=[json.loads(line) for line in (runner.run_dir/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    prepared=[row for row in events if row['kind']=='native_states_prepared']
    assert len(prepared)==6 and all(row['common_paid_setup'] and not row['policy_episode_timer_started'] for row in prepared)


def test_raw_source_check_handles_Dify_document_ID_and_direct_native_filename():
    spec={'required_logical_source_id':'sheet.xlsx','required_source_version':'v1'}
    binding={'workspace_id':'dataset','state_id':'HEALTHY','native_document_id':'doc-real',
             'logical_id':'sheet.xlsx','version':'v1'}
    output={'state_id':'HEALTHY','workspace_id':'dataset','native_response':{'metadata':{'retriever_resources':[
        {'document_id':'doc-real','document_name':'sheet.xlsx','segment_id':'chunk-other'}]}}}
    assert source_check(output,spec,[binding],'HEALTHY')['source_metadata_pass']
    output['native_response']={'sources':[{'id':'sheet.xlsx'}]}
    assert source_check(output,spec,[binding],'HEALTHY')['source_metadata_pass']
    assert not source_check(output,spec,[{**binding,'workspace_id':'foreign'}],'HEALTHY')['source_metadata_pass']


def test_primary_contract_is_independent_of_supplementary_source_failure():
    contracts=Contracts([{'id':'x','accepted_values':['0'],'required_logical_source_id':'missing'}])
    out={'answer':0,'completed':True,'state_id':'HEALTHY','workspace_id':'w','native_response':{'sources':[]}}
    for reference in (False,True):
        checked=contracts.check('x',out,bindings=[],state='HEALTHY',reference=reference)
        assert checked['primary_pass'] and not checked['source_metadata_pass']


def test_actual_contract_class_flattens_native_grouped_OpenWebUI_sources():
    contracts=Contracts([{'id':'task','accepted_values':['good'],
                         'required_logical_source_id':'record.txt','required_source_version':'v1'}])
    bindings=[{'workspace_id':'w','state_id':'HEALTHY','native_file_id':'file-one',
               'logical_source_id':'record.txt','version':'v1'},
              {'workspace_id':'w','state_id':'HEALTHY','native_file_id':'file-two',
               'logical_source_id':'other.txt','version':'v1'}]
    output={'answer':'good','completed':True,'state_id':'HEALTHY','workspace_id':'w',
            'native_response':{'sources':[{'document':['one','two'],
                'metadata':[{'file_id':'file-one'},{'file_id':'file-two'}]}]}}
    checked=contracts.check('task',output,bindings=bindings,state='HEALTHY',reference=True)
    assert checked['primary_pass'] and checked['source_metadata_pass']
    assert checked['flattened_native_context_count']==2


def test_source_guard_rejects_guidance_and_adapter_mutation(tmp_path):
    source=tmp_path/'rule.py';source.write_text('frozen source')
    adapter=tmp_path/'adapter.py';adapter.write_text('native adapter')
    freeze=tmp_path/'freeze.json';freeze.write_text(json.dumps({'phase':'EXTERNAL_V7',
        'frozen_files_sha256':{'rule.py':sha(source)}}))
    guard=FrozenGuidanceGuard(freeze,root=tmp_path,implementation_files=[],additional_source_files=[adapter])
    adapter.write_text('changed adapter')
    with pytest.raises(StudyIncident,match='source changed'): guard.check()
    adapter.write_text('native adapter');source.write_text('changed rule')
    with pytest.raises(StudyIncident,match='guidance/design changed'): guard.check()

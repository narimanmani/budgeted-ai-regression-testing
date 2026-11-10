from copy import deepcopy
import json
import pytest

from experiment.development_v8.execution.runner import ROOT, StudyIncident, sha
from experiment.development_v8.execution.resource_feasibility import (
    MainBudgetCampaign, select_block_budget, remaining_design_gate,
)

class Campaign:
    def __init__(self,run):
        self.run=run;self.count=355;self.gpu=200.;self.query_gpu=1.;self.queries=0
        self.auth={'native_query_cap':2929,'phase_gpu_cap_seconds':30000,
                   'shared_gpu_cap_seconds':43200,'prior_shared_gpu_seconds':9316.086159400991,
                   'max_native_timeout_seconds':600}
    def health(self):return {'counters':{'gpu_allocation_seconds_accounted':self.gpu,'chat_requests_reserved':self.count}}
    def _ledger(self):return ([{}]*self.count,None,None)
    def query(self,ident,metadata,operation):
        self.queries+=1;self.count+=1;self.gpu+=self.query_gpu
        return {'actual_value_retained':True},{'dispatch_safe_to_continue':True,
            'finished_counter':{'gpu_allocation_seconds_accounted':self.gpu},
            'native_query_units_reserved':1,'provider_join':{'gpu_allocation_seconds':self.query_gpu}}

def master(tmp_path):
    return {'block_order':[{'application_id':app,'repetition':rep,'output_dir':str(tmp_path/f'{app}-{rep}')}
                           for app,rep in [('openwebui',1),('dify',1),('openwebui',2),('dify',2)]],
            'main_start_native_ledger_entries':355,'main_start_gpu_allocation_seconds':200.,
            'whole_remaining_generation_allocation_seconds_ceiling':24000,
            'frozen_before_policy_outputs':True,
            'guidance_freeze_sha256':sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'),
            'episode_wall_formula':'ceil(10 + 1.5*K*max(old_pair_cost_estimates))'}

def test_whole_remaining_native_design_is_2272_not_old_2688(tmp_path):
    campaign=Campaign(tmp_path);document=master(tmp_path)
    selected=select_block_budget(campaign,document,'openwebui',1,tmp_path/'openwebui-1')
    assert selected['remaining_native_query_ceiling_at_block_start']==2272
    wrong=deepcopy(document);wrong['block_order'][0]['remaining_native_query_ceiling_at_block_start']=2688
    with pytest.raises(StudyIncident):select_block_budget(campaign,wrong,'openwebui',1,tmp_path/'openwebui-1')

def test_actual_debits_and_paid_old_projection_retain_whole_design(tmp_path):
    campaign=Campaign(tmp_path);document=master(tmp_path)
    selected=select_block_budget(campaign,document,'openwebui',1,tmp_path/'openwebui-1')
    gate=remaining_design_gate(campaign,selected,355)
    campaign.count+=48;campaign.gpu+=50
    observed=gate({'pair_cost_seconds':{'q1':4.},'feature_block_id':'paid-old'},[], 'before-calibration')
    assert observed['allowed']
    assert observed['root_declared_remaining_native_ceiling']==2224
    assert observed['actual_gpu_spent_since_block_start']==50
    assert observed['remaining_master_main_generation_room']==23950
    assert not observed['answer_or_reference_labels_used']

def test_completed_predecessor_debits_exact_568_without_reset(tmp_path):
    campaign=Campaign(tmp_path);document=master(tmp_path)
    complete=tmp_path/'openwebui-1/block';complete.mkdir(parents=True)
    (complete/'BLOCK_COMPLETION.json').write_text(json.dumps({'application_id':'openwebui','repetition':1,
        'error':None,'completed_trajectories':20,'physical_usage':{'native_query_units':568}}),encoding='utf-8')
    campaign.count+=568;campaign.gpu+=600
    selected=select_block_budget(campaign,document,'dify',1,tmp_path/'dify-1')
    assert selected['remaining_native_query_ceiling_at_block_start']==1704
    assert selected['whole_remaining_generation_allocation_seconds_ceiling']==23400
    campaign.count-=1
    with pytest.raises(StudyIncident):select_block_budget(campaign,document,'dify',1,tmp_path/'dify-1')

def test_nonpreemptible_overshoot_preserves_actual_receipt_and_stops(tmp_path):
    campaign=Campaign(tmp_path);wrapped=MainBudgetCampaign(campaign,master(tmp_path))
    campaign.query_gpu=25000
    output,receipt=wrapped.query('one',{},lambda timeout:None)
    assert output['actual_value_retained'] and receipt['provider_join']['gpu_allocation_seconds']==25000
    assert not receipt['dispatch_safe_to_continue']
    assert receipt['main_admission_guard']['measured_main_ceiling_overshoot_seconds']==1000
    assert (tmp_path/'MAIN_BUDGET_STOP.json').is_file()
    with pytest.raises(StudyIncident):wrapped.query('two',{},lambda timeout:None)
    assert campaign.queries==1

def test_short_remaining_lifetime_rejects_before_any_native_reservation(tmp_path):
    campaign=Campaign(tmp_path);wrapped=MainBudgetCampaign(campaign,master(tmp_path))
    campaign.gpu=200+23500
    with pytest.raises(StudyIncident):wrapped.query('one',{},lambda timeout:None)
    assert campaign.queries==0

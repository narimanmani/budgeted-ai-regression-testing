"""Prospective safeguards from global counters and paid OLD latency only."""
import math
from pathlib import Path
from experiment.development_v8.execution.runner import ROOT, StudyIncident, read, sha, utc, write_new


FIXED_BLOCK_ORDER=(('openwebui',1),('dify',1),('openwebui',2),('dify',2))


class MainBudgetCampaign:
    """Delegate actual accounting, adding a conservative per-query admission.

    A full native lifetime must fit in the remaining main/phase/shared room.
    Running provider calls are nonpreemptible; an actual overshoot is retained
    and stops continuation, never deleted or misreported as physical preemption.
    """
    def __init__(self,campaign,master):
        self._campaign=campaign
        self._baseline=master['main_start_gpu_allocation_seconds']
        self._cap=master['whole_remaining_generation_allocation_seconds_ceiling']
        self._reserve=campaign.auth['max_native_timeout_seconds']
        if self._cap!=24000 or not isinstance(self._reserve,(int,float)) or self._reserve!=600:
            raise StudyIncident('Main dispatch requires the fixed 24000-second admission ceiling and 600-second reserve')

    def __getattr__(self,name):return getattr(self._campaign,name)

    def _room(self):
        current=self._campaign.health()['counters']['gpu_allocation_seconds_accounted']
        if current<self._baseline:raise StudyIncident('Main cumulative GPU counter moved before its sealed baseline')
        used=current-self._baseline
        room=min(self._cap-used,self.auth['phase_gpu_cap_seconds']-current,
            self.auth['shared_gpu_cap_seconds']-self.auth['prior_shared_gpu_seconds']-current)
        return used,room

    def query(self,request_id,metadata,operation):
        before,room=self._room()
        if room<self._reserve:
            raise StudyIncident('No new native query: fewer than 600 seconds remain under the main/phase/shared admission ceilings')
        value,receipt=self._campaign.query(request_id,metadata,operation)
        # An unreconciled root receipt must still reach MeteredApplication's
        # durable raw record. A second health read may itself reject pending
        # work, so preserve the root's last actual counter on that path.
        after=receipt.get('finished_counter',{}).get('gpu_allocation_seconds_accounted',self._baseline+before)-self._baseline
        remaining=min(self._cap-after,room-(after-before));health_error=None
        if receipt.get('dispatch_safe_to_continue') is True:
            try:after,remaining=self._room()
            except Exception as exc:health_error=str(exc)
        overshoot=max(0.,after-self._cap)
        receipt={**receipt,'main_admission_guard':{
            'master_gpu_baseline':self._baseline,'main_admission_ceiling_seconds':self._cap,
            'reserved_native_lifetime_seconds':self._reserve,'actual_main_gpu_seconds_before':before,
            'actual_main_gpu_seconds_after':after,'remaining_main_phase_shared_room':remaining,
            'measured_main_ceiling_overshoot_seconds':overshoot,'physical_preemption_guaranteed':False,
            'post_operation_health_error':health_error,'actual_cost_reconciled':receipt.get('dispatch_safe_to_continue') is True and health_error is None}}
        if overshoot>0 or health_error is not None or receipt.get('dispatch_safe_to_continue') is not True:
            receipt['dispatch_safe_to_continue']=False
            stop=self._campaign.run/'MAIN_BUDGET_STOP.json'
            if not stop.exists():write_new(stop,{'at_utc':utc(),'request_id':request_id,
                'main_admission_guard':receipt['main_admission_guard'],'actual_native_receipt_preserved':True})
        return value,receipt


def select_block_budget(campaign,master,application,repetition,output_dir):
    """Select one prospectively frozen slot; never choose a favorable subset."""
    order=master.get('block_order',[])
    if [(r.get('application_id'),r.get('repetition')) for r in order]!=list(FIXED_BLOCK_ORDER):
        raise StudyIncident('Whole-main declaration must bind the exact prospective four-block order')
    paths=[Path(row['output_dir']).resolve() for row in order]
    if len(set(paths))!=4:raise StudyIncident('Main block outputs must be four distinct immutable directories')
    identity=(application,repetition)
    if identity not in FIXED_BLOCK_ORDER:raise StudyIncident('Unregistered main block')
    index=FIXED_BLOCK_ORDER.index(identity)
    if Path(output_dir).resolve()!=paths[index]:raise StudyIncident('Current block differs from its prospectively fixed output path')
    prior_physical=0
    for ordinal,path in enumerate(paths):
        complete=path/'block/BLOCK_COMPLETION.json'
        if ordinal<index:
            if not complete.is_file():raise StudyIncident('Preceding fixed-order main block has not completed')
            row=read(complete)
            if (row.get('application_id'),row.get('repetition'))!=FIXED_BLOCK_ORDER[ordinal] or row.get('error') is not None or row.get('completed_trajectories')!=20:
                raise StudyIncident('Preceding block is incomplete/foreign; no favorable continuation')
            prior_physical+=row['physical_usage']['native_query_units']
        elif complete.exists():raise StudyIncident('Current/future main slot was already completed')
    native_base=master.get('main_start_native_ledger_entries');gpu_base=master.get('main_start_gpu_allocation_seconds')
    if type(native_base) is not int or native_base<0 or isinstance(gpu_base,bool) or not isinstance(gpu_base,(int,float)) or not math.isfinite(gpu_base) or gpu_base<0:
        raise StudyIncident('Exact cumulative main-start native/GPU baselines required')
    entries=campaign._ledger()[0];current_gpu=campaign.health()['counters']['gpu_allocation_seconds_accounted']
    if len(entries)!=native_base+prior_physical or current_gpu<gpu_base:
        raise StudyIncident('Cumulative native/GPU baseline does not reconcile with preceding complete blocks')
    original=master.get('whole_remaining_generation_allocation_seconds_ceiling')
    if isinstance(original,bool) or not isinstance(original,(int,float)) or not math.isfinite(original) or original<=0:
        raise StudyIncident('Prospective whole-main seconds bound required')
    if original!=24000:raise StudyIncident('Root prospectively fixed the whole-main allocation ceiling at 24000 seconds')
    remaining=original-(current_gpu-gpu_base)
    if remaining<=0:raise StudyIncident('Prospective whole-main generation allocation exhausted')
    supplied=order[index].get('remaining_native_query_ceiling_at_block_start',568*(4-index))
    if supplied!=568*(4-index):raise StudyIncident('Slot native ceiling does not cover its exact remaining design')
    return {**master,'remaining_native_query_ceiling_at_block_start':568*(4-index),
        'whole_remaining_generation_allocation_seconds_ceiling':remaining,
        'master_original_whole_main_seconds_bound':original,'master_start_native_ledger_entries':native_base,
        'master_start_gpu_allocation_seconds':gpu_base,'selected_main_block_index':index,
        'prior_completed_main_physical_native_units':prior_physical}


def remaining_design_gate(campaign,budget_doc,block_started_native):
    freeze=sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json')
    if budget_doc.get('frozen_before_policy_outputs') is not True or budget_doc.get('guidance_freeze_sha256')!=freeze:
        raise StudyIncident('Whole-design continuation declaration must precede policy outputs')
    if budget_doc.get('episode_wall_formula')!='ceil(10 + 1.5*K*max(old_pair_cost_estimates))':
        raise StudyIncident('Episode wall safeguard differs from frozen implementation')
    native_bound=budget_doc.get('remaining_native_query_ceiling_at_block_start')
    seconds_bound=budget_doc.get('whole_remaining_generation_allocation_seconds_ceiling')
    if type(native_bound) is not int or not 568<=native_bound<=2272:
        raise StudyIncident('The complete remaining fixed main design must be priced')
    if (isinstance(seconds_bound,bool) or not isinstance(seconds_bound,(int,float))
            or not math.isfinite(seconds_bound) or seconds_bound<=0):
        raise StudyIncident('Finite prospective complete-remaining generation bound required')
    started_gpu=campaign.health()['counters']['gpu_allocation_seconds_accounted']

    def gate(features,plan,logical_phase):
        counter=campaign.health()['counters'];entries=campaign._ledger()[0]
        spent_native=len(entries)-block_started_native
        spent_gpu=counter['gpu_allocation_seconds_accounted']-started_gpu
        if spent_native<0 or spent_gpu<0:raise StudyIncident('Cumulative global counters moved backwards')
        pending=max(0,native_bound-spent_native)
        native_room=campaign.auth['native_query_cap']-len(entries)
        global_room=min(campaign.auth['phase_gpu_cap_seconds']-counter['gpu_allocation_seconds_accounted'],
            campaign.auth['shared_gpu_cap_seconds']-campaign.auth['prior_shared_gpu_seconds']-counter['gpu_allocation_seconds_accounted'])
        old_max=max(features['pair_cost_seconds'].values())
        if not math.isfinite(old_max) or old_max<=0:raise StudyIncident('Paid OLD cost estimate malformed')
        # Charge work already spent, rather than repeatedly requiring the full
        # original whole-design bound in addition to those already paid costs.
        root_remaining=max(0.,seconds_bound-spent_gpu)
        gpu_room=min(global_room,root_remaining)
        paid_old_projection=math.ceil(1.5*pending*old_max/2.)
        required=max(root_remaining,paid_old_projection)
        return {'allowed':pending<=native_room and root_remaining>0 and required<=gpu_room,'logical_phase':logical_phase,
            'guidance_freeze_sha256':freeze,'root_declared_remaining_native_ceiling':pending,
            'remaining_native_room':native_room,'root_remaining_generation_bound_after_actual_debit':root_remaining,
            'paid_old_latency_projected_remaining_bound':paid_old_projection,
            'required_remaining_generation_allocation_seconds':required,'remaining_generation_room':gpu_room,
            'remaining_phase_shared_generation_room':global_room,'remaining_master_main_generation_room':root_remaining,
            'actual_native_spent_since_block_start':spent_native,'actual_gpu_spent_since_block_start':spent_gpu,
            'paid_old_feature_block':features['feature_block_id'],'paid_old_max_pair_estimate':old_max,
            'actual_reserved_native_queries':len(entries),'actual_provider_generation_counter':counter['chat_requests_reserved'],
            'answer_or_reference_labels_used':False,'future_application_latency_guaranteed':False}
    return gate

"""Prospectively scoped native acquisition using unchanged factual checkers."""
from pathlib import Path
from copy import deepcopy
import time
from experiment.validation_v7.execution.runner import (
    MeteredApplication as PriorMeteredApplication, StudyIncident, metered_result,
    append, read, sha, utc, usage, write_new,
)
from experiment.validation_v7.execution.source_channels import CanonicalContracts

SCOPE_FIELDS=('cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256')
STATES=('HEALTHY','A_BAD','B_BAD')

class MeteredApplication(PriorMeteredApplication):
    def __init__(self,runtime,campaign,run_dir,application_id,repetition,scope,*,clock=time.perf_counter):
        super().__init__(runtime,campaign,run_dir,application_id,repetition,clock=clock)
        if set(scope)!=set(SCOPE_FIELDS) or any(not isinstance(scope[k],str) or not scope[k] for k in SCOPE_FIELDS):
            raise ValueError('Exact immutable cohort/prompt/input scope required')
        self.scope=deepcopy(scope)

    def _call(self,state,task,phase,owner,episode,operation):
        ident=self.ident(phase,f'{state}-{task}');started=self.clock()
        metadata={'application_id':self.application_id,'repetition':self.repetition,
            'trajectory_id':owner,'episode_index':episode,'state':state,'task':task,
            'state_id':state,'task_id':task,'phase':phase,'request_id':ident,**self.scope}
        def action(timeout):
            self.runtime.set_allocation_id(ident);self.runtime.set_operation_timeout(timeout)
            return operation(ident)
        self.attempts.append(metadata)
        try:output,receipt=metered_result(self.campaign.query(ident,metadata,action))
        except Exception as exc:
            append(self.run_dir/'UNRECONCILED_DISPATCHES.jsonl',{**metadata,'error':str(exc),'reservation_requires_root_ledger':True})
            raise
        row={**metadata,'elapsed_seconds':self.clock()-started,'native_output':output,
            'root_meter_receipt':receipt,'finished_at_utc':utc()}
        path=self.run_dir/'raw'/(ident+'.json');write_new(path,row)
        row['receipt_path']=str(path.resolve());row['receipt_sha256']=sha(path)
        append(self.run_dir/'query_index.jsonl',{k:v for k,v in row.items() if k not in ('native_output','root_meter_receipt')})
        self.query_records.append(row)
        if receipt.get('dispatch_safe_to_continue') is not True:raise StudyIncident('Unreconciled actual native work')
        if phase!='setup_probe':
            if any(output.get(k)!=v for k,v in self.scope.items()):raise StudyIncident('Native cohort/prompt/input scope mismatch')
        return row

    def metadata_step(self,label,operation):
        ident=self.ident('setup',label);started=self.clock()
        def action(timeout):
            self.runtime.set_allocation_id(ident);self.runtime.set_operation_timeout(timeout)
            result=operation()
            return result if isinstance(result,dict) else {'operation':label,'completed':True}
        value,receipt=metered_result(self.campaign.perform_setup(ident,action))
        row={'phase':'setup','request_id':ident,'label':label,'elapsed_seconds':self.clock()-started,
            'native_setup':value,'root_meter_receipt':receipt,**self.scope}
        write_new(self.run_dir/'setup_steps'/(ident+'.json'),row);self.operations.append(row)
        if receipt.get('dispatch_safe_to_continue') is not True:raise StudyIncident('Native metadata setup failed; retain the incident')
        return value

def acquire(meter,contracts,tasks,*,phase,guard,selected_by_state=None):
    if phase not in ('development','qualification','reference'):raise ValueError('Acquisition role required')
    if len(tasks)!=8 or len(set(tasks))!=8 or set(tasks)!=set(contracts.specs):raise ValueError('Exact eight-task frame required')
    planned=2*sum(len(selected_by_state.get(s,tasks) if selected_by_state else tasks) for s in STATES)
    outputs=[];error=None;started=meter.clock();owner=f'{meter.application_id}-{phase}-{meter.scope["prompt_candidate_id"]}'
    try:
        guard.check();meter.setup()
        for state in STATES:
            guard.check();meter.metadata_step('prepare-'+state,lambda state=state:meter.runtime.prepare_states([state]))
            chosen=selected_by_state.get(state,tasks) if selected_by_state else tasks
            for repeat in (1,2):
                for task in chosen:
                    guard.check();row=meter.query(state,task,phase,owner)
                    result={k:row[k] for k in ('application_id','state_id','task_id','request_id','receipt_path','receipt_sha256',*SCOPE_FIELDS)}
                    result['repetition']=repeat
                    result['reference_check']=contracts.check(task,row['native_output'],
                        bindings=meter.runtime.source_bindings(state),state=state,reference=True)
                    append(meter.run_dir/'sealed/reference_outputs.jsonl',result);outputs.append(result)
    except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
    finally:
        try:cleanup=meter.cleanup()
        except Exception as exc:cleanup={'error':str(exc)};error=error or {'type':'CleanupIncident','message':str(exc)}
    summary={'application_id':meter.application_id,'phase':phase,**meter.scope,
        'outputs':len(outputs),'planned_outputs':planned,'primary_passes':sum(r['reference_check']['primary_pass'] for r in outputs),
        'source_metadata_passes':sum(r['reference_check']['source_metadata_pass'] for r in outputs),
        'error':error,'physical_usage':usage([*meter.query_records,*meter.operations]),
        'wall_seconds':meter.clock()-started,'cleanup':cleanup}
    write_new(meter.run_dir/'REFERENCE_COMPLETION.json',summary)
    if error:raise StudyIncident('Separate native acquisition stopped: '+str(error))
    return summary

"""Episode-blocked native external evaluation with an injected root dispatcher.

No application/model work occurs at import. Reference files are never opened by
BlockRunner. Root supplies actual runtime, metering, contracts and impact builder.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time

from experiment.native_v3.common.contracts import operational_check
from experiment.native_v3.common.reference import reference_check
from experiment.validation_v7.guidance import policy

ROOT = Path(__file__).resolve().parents[3]
STATES = ('HEALTHY', 'A_BAD', 'B_BAD')
EPISODES = ((1, 'HEALTHY', 'A_BAD'), (2, 'A_BAD', 'HEALTHY'), (3, 'HEALTHY', 'B_BAD'))
FIXED_ARMS = tuple(policy.ARMS)
ALL_ARMS = (*FIXED_ARMS, 'CG1')
FIELDS = ('id', 'native_id', 'native_document_id', 'native_workspace_doc_id', 'docId',
          'file_id', 'fileId', 'document_id', 'documentId', 'source_id', 'title', 'name',
          'filename', 'document_name', 'location', 'url', 'native_url', 'docSource', 'native_doc_source', 'source')


def utc(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())


def append(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, ensure_ascii=True) + '\n')
        stream.flush(); os.fsync(stream.fileno())


class StudyIncident(RuntimeError): pass


class FrozenGuidanceGuard:
    def __init__(self, freeze_path=None, root=ROOT, additional_source_files=(), implementation_files=None):
        self.root = Path(root).resolve()
        self.path = Path(freeze_path or self.root / 'experiment/validation_v7/GUIDANCE_FREEZE.json')
        self.freeze = read(self.path); self.freeze_sha = sha(self.path)
        if self.freeze.get('phase') != 'EXTERNAL_V7': raise StudyIncident('Wrong guidance freeze phase')
        default_files=('experiment/validation_v7/execution/runner.py',
                       'experiment/validation_v7/execution/evaluate.py',
                       'experiment/validation_v7/control.py',
                       'experiment/native_v3/common/contracts.py','experiment/native_v3/common/reference.py')
        paths=[self.root/path for path in (default_files if implementation_files is None else implementation_files)]
        paths.extend(Path(path).resolve() for path in additional_source_files)
        self.implementation_sha256={str(path.resolve()):sha(path) for path in paths}
        self.check()

    def check(self):
        if sha(self.path) != self.freeze_sha: raise StudyIncident('Guidance freeze record changed')
        for relative, expected in self.freeze['frozen_files_sha256'].items():
            if sha(self.root / relative) != expected: raise StudyIncident('Frozen guidance/design changed: ' + relative)
        if self.freeze.get('case_search_frame_sha256') is not None:
            if sha(self.root/'experiment/validation_v7/CASE_SEARCH_FRAME.json')!=self.freeze['case_search_frame_sha256']:
                raise StudyIncident('Frozen external case-search frame changed')
        for path,expected in self.implementation_sha256.items():
            if sha(path)!=expected: raise StudyIncident('Execution/checker/adapter source changed after guard construction')


def aliases(row):
    return {str(row[key]) for key in FIELDS if isinstance(row.get(key), (str, int)) and row.get(key) != ''}


def raw_contexts(output):
    """Canonicalize only actual native source channels, not generated answers."""
    raw = output.get('native_response') or {}
    if not isinstance(raw, dict): return []
    value = raw.get('sources', raw.get('citations'))
    if value is None: value = (raw.get('metadata') or {}).get('retriever_resources')
    if value is None: value = output.get('returned_contexts', [])
    return value if isinstance(value, list) else []


def context_aliases(row):
    result = aliases(row)
    for field in ('metadata', 'source'):
        nested = row.get(field)
        if isinstance(nested, dict): result |= aliases(nested)
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict): result |= aliases(item)
    return result


def source_check(output, spec, bindings, expected_state):
    """Returned-source presence is supplementary; chunk IDs are not doc IDs."""
    workspace = output.get('workspace_id')
    identity_valid = output.get('state_id') == expected_state and workspace is not None
    rows = [row for row in bindings if row.get('workspace_id') == workspace
            and row.get('state_id', expected_state) == expected_state]
    mapped = []
    for context in raw_contexts(output):
        if not isinstance(context, dict):
            mapped.append({'status': 'malformed', 'logical_versions': []}); continue
        candidates = context_aliases(context)
        found = []
        for binding in rows:
            # Direct raw logical filename IDs are valid only through an actual
            # indexed upload binding in the expected state/workspace.
            authoritative = aliases(binding)
            for field in ('logical_id', 'logical_source_id'):
                if binding.get(field): authoritative.add(str(binding[field]))
            if candidates.intersection(authoritative): found.append(binding)
        logical = sorted({(row.get('logical_source_id', row.get('logical_id')),
                           row.get('version', row.get('data_version'))) for row in found}, key=str)
        logical = [list(item) for item in logical if item[0] is not None]
        mapped.append({'status': 'unique_logical_match' if len(logical) == 1 else
                       ('unresolved' if not logical else 'ambiguous'), 'logical_versions': logical})
    observed = {tuple(item) for row in mapped if row['status'] == 'unique_logical_match'
                for item in row['logical_versions']}
    required = spec.get('required_logical_source_id'); version = spec.get('required_source_version')
    source_pass = identity_valid and (required is None or any(
        logical == required and (version is None or version == data_version) for logical, data_version in observed))
    return {'source_metadata_pass': bool(source_pass), 'source_identity_valid': identity_valid,
            'source_context_mappings': mapped, 'source_unresolved_or_ambiguous': sum(
                row['status'] != 'unique_logical_match' for row in mapped),
            'source_property_is_primary': False, 'source_semantics': 'Actual returned-context metadata, not inline factual support'}


class Contracts:
    def __init__(self, document):
        rows = document.get('contracts', document) if isinstance(document, dict) else document
        self.specs = {row['id']: row for row in rows}
        if len(self.specs) != len(rows): raise ValueError('Duplicate contract identity')

    def check(self, task_id, output, *, bindings, state, reference=False):
        spec = self.specs[task_id]
        contract = {'id': task_id, 'version': spec.get('data_version', 'v1'),
                    'expected_behavior': 'answer', 'accepted_answers': spec['accepted_values']}
        primary = {'answer': output.get('answer'), 'completed': output.get('completed') is True, 'sources': []}
        result = (reference_check if reference else operational_check)(primary, contract)
        return {'primary_pass': result['passed'], 'primary_reasons': result['reasons'], 'checker': result['checker'],
                **source_check(output, spec, bindings, state)}


def metered_result(value):
    if not isinstance(value, tuple) or len(value) != 2: raise StudyIncident('Root must return value and actual cost receipt')
    output, receipt = value
    if not isinstance(receipt, dict): raise StudyIncident('Missing actual root receipt')
    return output, receipt


class MeteredApplication:
    """One native application/repetition; no free or unreserved dispatch."""
    def __init__(self, runtime, campaign, run_dir, application_id, repetition, *, clock=time.perf_counter):
        self.runtime, self.campaign = runtime, campaign
        self.run_dir = Path(run_dir); self.run_dir.mkdir(parents=True, exist_ok=False)
        self.application_id, self.repetition, self.clock = application_id, repetition, clock
        self.counter = 0; self.query_records = []; self.operations = []; self.attempts = []

    def ident(self, phase, suffix):
        self.counter += 1
        return f'{self.application_id}-r{self.repetition}-{self.counter:05d}-{phase}-{suffix}'

    def setup(self):
        ident = self.ident('setup', 'metadata-index-only'); start = self.clock()
        def action(timeout):
            self.runtime.set_allocation_id(ident); self.runtime.set_operation_timeout(timeout)
            return self.runtime.setup()
        output, receipt = metered_result(self.campaign.perform_setup(ident, action))
        row = {'request_id': ident, 'phase': 'setup', 'elapsed_seconds': self.clock()-start,
               'native_setup': output, 'root_meter_receipt': receipt}
        write_new(self.run_dir/'SETUP.json', row); self.operations.append(row)
        if receipt.get('dispatch_safe_to_continue') is not True: raise StudyIncident('Setup accounting invalid; no further dispatch')
        return output

    def _call(self, state, task, phase, owner, episode, operation):
        ident = self.ident(phase, f'{state}-{task}'); start = self.clock()
        metadata = {'application_id': self.application_id, 'repetition': self.repetition,
                    'trajectory_id': owner, 'episode_index': episode, 'state': state, 'task': task,
                    'state_id': state, 'task_id': task, 'phase': phase, 'request_id': ident}
        def action(timeout):
            self.runtime.set_allocation_id(ident); self.runtime.set_operation_timeout(timeout)
            return operation(ident)
        self.attempts.append(metadata)
        try:
            output, receipt = metered_result(self.campaign.query(ident, metadata, action))
        except Exception as exc:
            append(self.run_dir/'UNRECONCILED_DISPATCHES.jsonl', {**metadata, 'error':str(exc), 'reservation_requires_root_ledger':True})
            raise
        row = {**metadata, 'elapsed_seconds': self.clock()-start, 'native_output': output,
               'root_meter_receipt':receipt, 'finished_at_utc':utc()}
        path=self.run_dir/'raw'/(ident+'.json'); write_new(path,row)
        row['receipt_path']=str(path.resolve());row['receipt_sha256']=sha(path)
        append(self.run_dir/'query_index.jsonl',{k:v for k,v in row.items() if k not in ('native_output','root_meter_receipt')})
        self.query_records.append(row)
        if receipt.get('dispatch_safe_to_continue') is not True: raise StudyIncident('Unreconciled actual work; stop native dispatch')
        return row

    def query(self, state, task, phase, owner, episode=0):
        if state not in STATES: raise ValueError('Unknown canonical native state')
        def query_and_bind(ident):
            output=self.runtime.query(state,task,ident)
            if not isinstance(output,dict): return output
            # Actual upload/index bindings are runtime metadata, never expected
            # source hints. Preserve the raw native payload byte-for-byte inside
            # native_response while snapshotting the authoritative state map.
            return {**output,'source_bindings':deepcopy(self.runtime.source_bindings(state)),
                    'source_bindings_origin':'runtime_state_upload_index_receipts'}
        row=self._call(state,task,phase,owner,episode,query_and_bind)
        if not isinstance(row['native_output'],dict) or row['native_output'].get('valid_native_response') is not True:
            raise StudyIncident('Native response invalid; not a product failure')
        return row

    def reserved_probe(self, operation, owner='infrastructure'):
        """Credential generation probes consume native slack; setup itself is chat0."""
        return self._call('INFRA','PROVIDER_VALIDATE','setup_probe',owner,0,operation)

    def cleanup(self):
        start=self.clock();output=self.runtime.cleanup()
        row={'phase':'cleanup','elapsed_seconds':self.clock()-start,'native_cleanup':output}
        write_new(self.run_dir/'CLEANUP.json',row);self.operations.append(row);return row


def usage(records):
    result={'native_query_units':0,'provider_chat_boundaries':0,'embedding_boundaries':0,
            'gpu_allocation_seconds':0.0,'embedding_cpu_seconds':0.0}
    for row in records:
        receipt=row.get('root_meter_receipt',{});join=receipt.get('provider_join',{})
        result['native_query_units']+=receipt.get('native_query_units_reserved',0)
        for source,dest in [('chat_boundary_attempts','provider_chat_boundaries'),
                            ('embedding_boundary_attempts','embedding_boundaries'),
                            ('gpu_allocation_seconds','gpu_allocation_seconds'),
                            ('embedding_cpu_seconds_recorded','embedding_cpu_seconds')]:
            number=join.get(source,0)
            if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or number<0:
                raise StudyIncident('Actual cost cannot be unknown/negative/malformed')
            result[dest]+=number
    return result


def profile_feature(row):
    output=row['native_output']
    return {'task_id':row['task_id'],'request_id':row['request_id'],'state_id':row['state_id'],
            'feature_block_id':row['trajectory_id'],'origin':'paid_old_native_contexts',
            'elapsed_seconds':row['elapsed_seconds'],'workspace_id':output.get('workspace_id'),
            'returned_contexts':raw_contexts(output),'source_bindings':output.get('source_bindings',[]),
            'native_receipt_path':output.get('receipt_path'),
            'root_joined_receipt_path':row['receipt_path'],'root_joined_receipt_sha256':row['receipt_sha256']}


def trajectory_plan(application_id,repetition):
    plan=[{'arm':arm,'budget_id':budget,'history_regime':regime,
           'trajectory_id':f'{application_id}-r{repetition}-{budget}-{regime}-{arm}'}
          for budget in ('LOW','HIGH') for regime in ('COLD','WARM') for arm in ALL_ARMS]
    return plan if repetition==1 else list(reversed(plan))


class BlockRunner:
    def __init__(self,meter,contracts,task_ids,feature_builder,changed_tokens_by_episode,
                 run_dir,*,guard=None,clock=None,affordability_gate=None):
        self.meter,self.contracts,self.tasks,self.builder=meter,contracts,tuple(task_ids),feature_builder
        self.changes={int(k):policy.tokens(v) for k,v in changed_tokens_by_episode.items()}
        self.run_dir=Path(run_dir);self.run_dir.mkdir(parents=True,exist_ok=True)
        self.clock=clock or meter.clock;self.guard=guard or FrozenGuidanceGuard()
        self.affordability_gate=affordability_gate
        self.features={};self.histories={};self.trajectories={};self.closed={1:set(),2:set(),3:set()}
        self.impact_processing_seconds=[]
        self.used=False

    def event(self,kind,**values):
        append(self.run_dir/'events.jsonl',{'kind':kind,'at_utc':utc(),'elapsed_seconds':self.clock()-self.started,**values})

    def _profile(self,state,release_episode,plan):
        if state=='A_BAD' and self.closed[1]!={row['trajectory_id'] for row in plan}:
            raise StudyIncident('A_BAD features cannot be released before ALL20 episode-1 trajectories close')
        if state not in ('HEALTHY','A_BAD') or state in self.features: raise StudyIncident('Unexpected/duplicate old-state profile')
        self.guard.check();owner=f'{self.meter.application_id}-r{self.meter.repetition}-OLD-{state}'
        records=[];started=self.clock()
        for repetition in range(1,4):
            for task in self.tasks:
                row=self.meter.query(state,task,'profile',owner,release_episode)
                records.append(row)
        costs=policy.paired_cost_profile({task:[row['elapsed_seconds'] for row in records if row['task_id']==task] for task in self.tasks})
        features={'feature_block_id':owner,'state_id':state,'release_episode':release_episode,
                  'application_id':self.meter.application_id,'repetition':self.meter.repetition,
                  'task_ids':list(self.tasks),'pair_cost_seconds':costs,
                  'observations':[profile_feature(row) for row in records],
                  'actual_shared_physical_usage':usage(records),'acquisition_wall_seconds':self.clock()-started,
                  'recorded_at_utc':utc()}
        path=self.run_dir/'features'/(state+'.json');write_new(path,features)
        features['receipt_path']=str(path.resolve());features['receipt_sha256']=sha(path)
        self.features[state]=features
        self.event('old_feature_block_released',state_id=state,release_episode=release_episode,
                   feature_block_id=owner,closed_episode1=sorted(self.closed[1]),
                   receipt_path=features['receipt_path'],receipt_sha256=features['receipt_sha256'])
        return features

    def _impact(self,features,episode):
        before=self.clock()
        value=self.builder(deepcopy(features),deepcopy(self.meter.runtime.source_bindings(features['state_id'])),
                           list(self.changes[episode]),episode)
        # The frozen policy validates the strict projection, including provenance
        # and no-future-information markers. Raw context evidence stays separate.
        admitted,reason=policy.checked_impact(value,self.tasks,self.changes[episode],
                                              features['feature_block_id'],episode)
        path=self.run_dir/'impact'/(f'{features["state_id"]}-E{episode}.json')
        processing=self.clock()-before;self.impact_processing_seconds.append(processing)
        write_new(path,{'impact':value,'processing_seconds':processing,
                        'feature_receipt_sha256':features['receipt_sha256'],'admitted':admitted,'reason':reason})
        return value,admitted,{'receipt_path':str(path.resolve()),'receipt_sha256':sha(path)}

    def _allowance(self,features,plan,logical_phase):
        if self.affordability_gate is None: raise StudyIncident('Root whole-continuation affordability gate is required')
        allowance=self.affordability_gate(deepcopy(features),deepcopy(plan),logical_phase)
        if not isinstance(allowance,dict) or allowance.get('allowed') is not True:
            raise StudyIncident('Complete remaining continuation not prospectively affordable')
        write_new(self.run_dir/'allowances'/(logical_phase+'.json'),allowance)
        return allowance

    def _pair(self,trajectory,old,new,task,phase,episode,deadline):
        owner=trajectory['trajectory_id']
        before=self.meter.query(old,task,phase,owner,episode)
        if self.clock()>deadline:
            self.event('late_old_only',trajectory_id=owner,episode_index=episode,task_id=task,request_id=before['request_id'])
            return None
        after=self.meter.query(new,task,phase,owner,episode)
        old_check=self.contracts.check(task,before['native_output'],bindings=self.meter.runtime.source_bindings(old),state=old)
        new_check=self.contracts.check(task,after['native_output'],bindings=self.meter.runtime.source_bindings(new),state=new)
        pair={'trajectory_id':owner,'episode_index':episode,'phase':phase,'task_id':task,
              'old_state':old,'new_state':new,'old_request_id':before['request_id'],'new_request_id':after['request_id'],
              'old_receipt_path':before['receipt_path'],'old_receipt_sha256':before['receipt_sha256'],
              'new_receipt_path':after['receipt_path'],'new_receipt_sha256':after['receipt_sha256'],
              'old_primary_pass':old_check['primary_pass'],'new_primary_pass':new_check['primary_pass'],
              'old_source_metadata_pass':old_check['source_metadata_pass'],
              'new_source_metadata_pass':new_check['source_metadata_pass'],
              'primary_alarm_candidate':old_check['primary_pass'] and not new_check['primary_pass']}
        # Durable selected judgment is part of the operational arrival, not a
        # later report timestamp. Late work is charged and cannot seed history.
        self.event('selected_pair_judged',**pair)
        arrived=self.clock()
        pair['judgment_observed_elapsed_seconds']=arrived-self.started
        pair['timely']=arrived<=deadline
        pair['primary_alarm_credited']=pair['timely'] and pair['primary_alarm_candidate']
        path=self.run_dir/'trajectories'/owner/'pairs'/(f'{phase}-E{episode}-{task}.json')
        write_new(path,pair)
        pair['receipt_path']=str(path.resolve());pair['receipt_sha256']=sha(path)
        return pair

    def _history_events(self,trajectory,pairs):
        return [{'source':'own_observed_paired_execution','trajectory_id':trajectory['trajectory_id'],
                 'task_id':row['task_id'],'episode_index':row['episode_index'],'selected':True,
                 'timely':row['timely'],'old_primary_pass':row['old_primary_pass'],
                 'new_primary_pass':row['new_primary_pass'],
                 'changed_tokens':self.changes[1] if row['episode_index']==0 else self.changes[row['episode_index']],
                 'receipt_sha256':row['receipt_sha256']} for row in pairs]

    def run(self):
        if self.used: raise StudyIncident('One-use block runner cannot resume or overwrite work')
        self.used=True;self.started=self.clock();error=None;setup=None
        if len(self.tasks)!=12 or set(self.contracts.specs)!=set(self.tasks) or set(self.changes)!={1,2,3}:
            raise StudyIncident('Frozen external frame requires12 tasks and3 declared changes')
        plan=trajectory_plan(self.meter.application_id,self.meter.repetition)
        write_new(self.run_dir/'BLOCK_EXECUTION_RESERVATION.json',{'created_at_utc':utc(),'plan':plan,
            'source_guard_required':True,'guidance_freeze_sha256':getattr(self.guard,'freeze_sha',None),
            'implementation_sha256':getattr(self.guard,'implementation_sha256',{})})
        try:
            self.guard.check();setup=self.meter.setup()
            for item in plan:
                self.trajectories[item['trajectory_id']]={**item,'application_id':self.meter.application_id,
                    'repetition':self.meter.repetition,'calibration_pairs':[],'selected_pairs':[],
                    'decisions':[],'episodes':[],'own_calibration_wall_seconds':0.0,
                    'changed_tokens_by_episode':{str(k):v for k,v in self.changes.items()},'error':None}
                self.histories[item['trajectory_id']]=[]
            healthy=self._profile('HEALTHY',1,plan)
            allowance=self._allowance(healthy,plan,'before_own_calibration')
            write_new(self.run_dir/'CONTINUATION_ALLOWANCE.json',allowance)
            for item in plan:
                trajectory=self.trajectories[item['trajectory_id']]
                if item['history_regime']=='WARM':
                    calibration_started=self.clock()
                    deadline=self.clock()+math.ceil(60+1.5*12*max(healthy['pair_cost_seconds'].values()))
                    pairs=[]
                    for task in self.tasks:
                        pair=self._pair(trajectory,'HEALTHY','A_BAD',task,'calibration',0,deadline)
                        if pair is None or not pair['timely']: raise StudyIncident('Own warm calibration incomplete or late')
                        pairs.append(pair)
                    trajectory['calibration_pairs']=pairs
                    self.histories[item['trajectory_id']]=self._history_events(trajectory,pairs)
                    trajectory['own_calibration_wall_seconds']=self.clock()-calibration_started
            for episode,old,new in EPISODES:
                self.guard.check()
                features=self.features.get(old) or self._profile(old,episode,plan)
                if features['release_episode']>episode: raise StudyIncident('Future old-state features exposed')
                self._allowance(features,plan,f'before_episode_{episode}')
                impact,admitted,impact_receipt=self._impact(features,episode)
                for item in plan:
                    start=self.clock()
                    self.guard.check();owner=item['trajectory_id'];trajectory=self.trajectories[owner]
                    saved=read(features['receipt_path'])
                    if sha(features['receipt_path'])!=features['receipt_sha256'] or any(features[k]!=v for k,v in saved.items()):
                        raise StudyIncident('Common paid old-state features changed after release')
                    history=self.histories[owner];ceiling=2 if item['budget_id']=='LOW' else 4
                    wall=math.ceil(10+1.5*ceiling*max(features['pair_cost_seconds'].values()))
                    deadline=start+wall
                    if item['arm']=='CG1':
                        decision=policy.choose(list(self.tasks),features['pair_cost_seconds'],impact,history,
                            trajectory_id=owner,feature_block_id=features['feature_block_id'],episode_index=episode,
                            changed_tokens=self.changes[episode],pair_limit=ceiling)
                        chosen=decision['chosen_arm'];ordered=decision['nominal_ordered_task_ids']
                    else:
                        positive=policy.checked_history(history,self.tasks,owner,episode)
                        counts=dict(Counter(row['task_id'] for row in positive))
                        chosen=item['arm'];ordered=policy.rank_arm(self.tasks,features['pair_cost_seconds'],admitted,counts,chosen)
                        decision={'chosen_arm':chosen,'fixed_baseline':True,'all_positive_history_counts':counts,
                                  'nominal_ordered_task_ids':ordered,'nominal_prefix_task_ids':ordered[:ceiling]}
                    decision={**decision,'trajectory_id':owner,'episode_index':episode,'old_state':old,'new_state':new,
                        'changed_tokens':self.changes[episode],
                        'feature_block_id':features['feature_block_id'],'feature_receipt_sha256':features['receipt_sha256'],
                        'feature_receipt_path':features['receipt_path'],'impact_receipt':impact_receipt,
                        'history_before_decision':deepcopy(history),
                        'admitted_task_ids':admitted if policy.ARMS[chosen][0] else list(self.tasks),
                        'pair_limit':ceiling,'wall_seconds':wall,'decision_before_native_new_query':True,
                        'episode_start_elapsed_seconds':start-self.started,
                        'deadline_elapsed_seconds':deadline-self.started}
                    # This immutable plan exists before ANY selected old/new query.
                    write_new(self.run_dir/'trajectories'/owner/'decisions'/(f'E{episode}.json'),decision)
                    self.event('decision_recorded',**decision);trajectory['decisions'].append(decision)
                    pairs=[];attempts=0;skips=[]
                    for task in ordered:
                        if attempts>=ceiling or self.clock()>=deadline: break
                        if self.clock()+features['pair_cost_seconds'][task]>deadline:
                            skips.append(task);continue
                        attempts+=1
                        pair=self._pair(trajectory,old,new,task,'comparison',episode,deadline)
                        if pair is None: break
                        pairs.append(pair)
                        if not pair['timely']: break
                    trajectory['selected_pairs'].extend(pairs)
                    self.histories[owner].extend(self._history_events(trajectory,pairs))
                    end={'episode_index':episode,'paired_attempts':attempts,'estimated_fit_skips':skips,
                         'wall_seconds':self.clock()-start,'deadline_overrun_seconds':max(0.,self.clock()-deadline),
                         'nominal_actual_selection_equal':[row['task_id'] for row in pairs]==decision['nominal_prefix_task_ids']}
                    trajectory['episodes'].append(end);self.closed[episode].add(owner)
                    self.event('episode_closed',trajectory_id=owner,**end)
                if self.closed[episode]!={row['trajectory_id'] for row in plan}: raise StudyIncident('Incomplete logical episode block')
            self.guard.check()
        except Exception as exc:
            error={'type':type(exc).__name__,'message':str(exc)}
            self.event('block_incident',error=error)
        finally:
            try: cleanup=self.meter.cleanup()
            except Exception as exc:
                cleanup={'error':str(exc)};error=error or {'type':'CleanupIncident','message':str(exc)}
        for owner,trajectory in self.trajectories.items():
            own=[row for row in self.meter.query_records if row['trajectory_id']==owner]
            trajectory['own_query_receipts']=[{key:row[key] for key in
                ('request_id','state_id','task_id','phase','receipt_path','receipt_sha256')} for row in own]
            trajectory['actual_own_physical_usage']=usage(own)
            trajectory['allocated_shared_feature_usage']=usage([row for row in self.meter.query_records if row['phase']=='profile'])
            trajectory['allocated_common_setup_usage']=usage([row for row in self.meter.operations if row['phase']=='setup'])
            trajectory['allocated_common_setup_wall_seconds']=sum(row['elapsed_seconds'] for row in self.meter.operations if row['phase']=='setup')
            trajectory['allocated_common_cleanup_wall_seconds']=cleanup.get('elapsed_seconds')
            trajectory['allocated_feature_acquisition_wall_seconds']=sum(row['acquisition_wall_seconds'] for row in self.features.values())
            trajectory['allocated_shared_impact_processing_seconds']=sum(self.impact_processing_seconds)
            trajectory['own_comparison_wall_seconds']=sum(row['wall_seconds'] for row in trajectory['episodes'])
            trajectory['allocated_standalone_wall_seconds']=(trajectory['own_calibration_wall_seconds']+
                trajectory['own_comparison_wall_seconds']+trajectory['allocated_common_setup_wall_seconds']+
                (trajectory['allocated_common_cleanup_wall_seconds'] or 0.0)+
                trajectory['allocated_feature_acquisition_wall_seconds']+trajectory['allocated_shared_impact_processing_seconds'])
            trajectory['allocated_wall_is_component_sum_not_dedicated_process_observation']=True
            trajectory['allocated_standalone_native_query_units']=(trajectory['actual_own_physical_usage']['native_query_units']+
                trajectory['allocated_shared_feature_usage']['native_query_units']+
                trajectory['allocated_common_setup_usage']['native_query_units'])
            trajectory['allocated_costs_are_not_additional_physical_queries']=True
            trajectory['final_history']=self.histories[owner]
            trajectory['error']=error
            trajectory['complete']=error is None and len(trajectory['episodes'])==3
            write_new(self.run_dir/'trajectories'/owner/'TRAJECTORY_RESULT.json',trajectory)
        result={'application_id':self.meter.application_id,'repetition':self.meter.repetition,
                'completed_trajectories':sum(row.get('complete',False) for row in self.trajectories.values()),
                'planned_trajectories':20,'error':error,'physical_usage':usage([*self.meter.query_records,*self.meter.operations]),
                'wall_seconds':self.clock()-self.started,'logical_episode_closures':{str(k):sorted(v) for k,v in self.closed.items()},
                'common_old_feature_profiles':{k:{'receipt_path':v['receipt_path'],'receipt_sha256':v['receipt_sha256']} for k,v in self.features.items()},
                'reference_bank_read_by_native_runner':False,'cleanup':cleanup}
        write_new(self.run_dir/'BLOCK_COMPLETION.json',result)
        if error: raise StudyIncident(str(error))
        return result


def acquire_reference(meter,contracts,task_ids,*,passes=2,states=STATES,
                      selected_by_state=None,phase='reference',guard=None):
    """Separately metered acquisition; no reference result enters BlockRunner."""
    started=meter.clock();outputs=[];error=None
    guard=guard or FrozenGuidanceGuard()
    owner=f'{meter.application_id}-{phase}'
    try:
        guard.check()
        meter.setup()
        for state in states:
            chosen=selected_by_state.get(state,task_ids) if selected_by_state is not None else task_ids
            for repetition in range(1,passes+1):
                for task in chosen:
                    guard.check()
                    row=meter.query(state,task,phase,owner,0)
                    result={key:row[key] for key in ('application_id','state_id','task_id','request_id',
                                                     'receipt_path','receipt_sha256')}
                    result['repetition']=repetition
                    result['reference_check']=contracts.check(task,row['native_output'],
                        bindings=meter.runtime.source_bindings(state),state=state,reference=True)
                    append(meter.run_dir/'sealed/reference_outputs.jsonl',result);outputs.append(result)
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
    finally:
        try: cleanup=meter.cleanup()
        except Exception as exc:
            cleanup={'error':str(exc)};error=error or {'type':'CleanupIncident','message':str(exc)}
    summary={'application_id':meter.application_id,'phase':phase,'outputs':len(outputs),
        'planned_outputs':passes*sum(len(selected_by_state.get(state,task_ids) if selected_by_state else task_ids) for state in states),
        'primary_passes':sum(row['reference_check']['primary_pass'] for row in outputs),
        'source_metadata_passes':sum(row['reference_check']['source_metadata_pass'] for row in outputs),
        'error':error,'physical_usage':usage([*meter.query_records,*meter.operations]),
        'wall_seconds':meter.clock()-started,'cleanup':cleanup}
    write_new(meter.run_dir/'REFERENCE_COMPLETION.json',summary)
    if error: raise StudyIncident('Separate native acquisition stopped: '+str(error))
    return summary

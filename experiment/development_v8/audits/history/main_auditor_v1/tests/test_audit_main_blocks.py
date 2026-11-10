"""Pure completed-frame/barrier/cost-source checks; no native observations."""
from copy import deepcopy
import json
import pytest
from experiment.development_v8.audits.audit_main_blocks import (
    complete_frame,event_barrier,profile_frame,common_features,verify_file_map,audit,
)
from experiment.development_v8.audits.audit_acquisition import sha

def frame():
    plan=[{'trajectory_id':'T'+str(i)} for i in range(20)]
    ids=[row['trajectory_id'] for row in plan]
    return {'error':None,'completed_trajectories':20,'planned_trajectories':20,
        'logical_episode_closures':{str(i):ids for i in (1,2,3)},
        'physical_usage':{'native_query_units':568}},plan

def test_full_frame_has_all_twenty_closures_and_bounded_physical_work():
    completion,plan=frame();assert len(complete_frame(completion,plan))==20
    completion['physical_usage']['native_query_units']=569
    with pytest.raises(ValueError,match='ceiling'):complete_frame(completion,plan)

def test_missing_closure_and_duplicate_trajectory_plan_fail():
    completion,plan=frame();completion['logical_episode_closures']['2']=completion['logical_episode_closures']['2'][:-1]
    with pytest.raises(ValueError,match='close'):complete_frame(completion,plan)
    completion,plan=frame();plan[-1]=plan[0]
    with pytest.raises(ValueError,match='Distinct'):complete_frame(completion,plan)

def test_partial_block_is_rejected_before_any_raw_answer_read(tmp_path,monkeypatch):
    directory=tmp_path/'block';directory.mkdir()
    (directory/'BLOCK_COMPLETION.json').write_text(json.dumps({'error':None,'completed_trajectories':19,'planned_trajectories':20}),encoding='utf-8')
    with pytest.raises(ValueError,match='raw answers are not opened'):
        audit(tmp_path,tmp_path,tmp_path/'unread-reference',tmp_path/'unread-config',tmp_path/'unread-freeze')

def barrier():
    ids={'T'+str(i) for i in range(20)}
    events=[{'kind':'old_feature_block_released','state_id':'HEALTHY','at_utc':'2026-11-01T00:00:00+00:00'}]
    events += [{'kind':'episode_closed','episode_index':1,'trajectory_id':ident,'at_utc':'2026-11-01T00:01:00+00:00'} for ident in sorted(ids)]
    events += [{'kind':'old_feature_block_released','state_id':'A_BAD','closed_episode1':sorted(ids),'at_utc':'2026-11-01T00:02:00+00:00'}]
    return ids,events

def test_a_profile_requires_all_twenty_earlier_episode1_closures():
    ids,events=barrier();releases,closed=event_barrier(events,ids)
    assert set(releases)=={'HEALTHY','A_BAD'} and closed.minute==1
    late=events.pop();events.insert(20,late)
    with pytest.raises(ValueError,match='barrier'):event_barrier(events,ids)

def test_a_release_cannot_claim_a_missing_closure_proof():
    ids,events=barrier();events[-1]['closed_episode1']=sorted(ids)[:-1]
    with pytest.raises(ValueError,match='omits'):event_barrier(events,ids)

def profiles():
    tasks=['q'+str(i) for i in range(8)]
    raw=[{'phase':'profile','state_id':state,'task_id':task} for state in ('HEALTHY','A_BAD') for task in tasks for repeat in range(3)]
    return tasks,raw

def test_profiles_require_paid_three_passes_of_each_old_task_state():
    tasks,raw=profiles();assert len(profile_frame(raw,tasks))==48
    raw[-1]['state_id']='B_BAD'
    with pytest.raises(ValueError,match='profiles'):profile_frame(raw,tasks)
    tasks,raw=profiles();raw[-1]=deepcopy(raw[0])
    with pytest.raises(ValueError,match='profiles'):profile_frame(raw,tasks)

def test_every_strategy_receives_identical_common_feature_and_impact_hashes():
    results=[{'decisions':[{'episode_index':episode,'feature_receipt_sha256':'feature'+str(episode),
        'impact_receipt':{'receipt_sha256':'impact'+str(episode)}} for episode in (1,2,3)]} for i in range(20)]
    assert len(common_features(results))==3
    results[-1]['decisions'][1]['feature_receipt_sha256']='policy-specific-future-feature'
    with pytest.raises(ValueError,match='same immutable'):common_features(results)

def test_source_freeze_verification_detects_changed_bytes(tmp_path):
    path=tmp_path/'source.txt';path.write_text('Original frozen bytes',encoding='utf-8')
    mapping={'source.txt':sha(path)}
    assert verify_file_map(mapping,tmp_path)==1
    path.write_text('Changed after decisions',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):verify_file_map(mapping,tmp_path)

"""Synthetic saved-observation fixtures; never native study observations."""
import copy
import json
from pathlib import Path
import pytest
from experiment.development_v8.execution.runner import acquire_reference, Contracts, MeteredApplication, sha, StudyIncident
from experiment.development_v8.execution.evaluate import (
    evaluate_trajectory, evaluate_campaign, matched_strata, reference_truth,
)
from experiment.development_v8.execution.test_runner import fixture, Runtime, Clock, Campaign, SCOPE


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    directory=tmp_path_factory.mktemp('v8-synthetic-saved-observations')
    runner,meter,*_=fixture(directory/'operation');runner.run()
    clock=Clock();runtime=Runtime(clock)
    reference=MeteredApplication(runtime,Campaign(),directory/'reference','software-fixture',1,scope=SCOPE,clock=clock)
    completion=acquire_reference(reference,runner.contracts,list(runner.tasks))
    return directory,runner,reference,completion


def test_complete_independent_reference_and_all_twenty_primary_rechecks(completed):
    directory,runner,reference,completion=completed
    assert completion['outputs']==48 and completion['primary_passes']==44
    assert completion['source_metadata_passes']==48
    truth,cells=reference_truth(reference.run_dir,runner.contracts)
    assert all(row['status']=='stable' for row in truth.values())
    assert sum(row['classification']=='regression' for row in cells)==2
    checked=[]
    for path in (runner.run_dir/'trajectories').glob('*/TRAJECTORY_RESULT.json'):
        checked.append(evaluate_trajectory(path,runner.contracts,cells))
    assert len(checked)==20
    assert all(not row['own_pair_reference_mismatches'] and not row['source_recheck_mismatches'] for row in checked)
    assert sum(row['actual_own_physical_usage']['native_query_units'] for row in checked)==520
    for row in checked:
        assert row['allocated_standalone_native_query_units']==row['actual_own_physical_usage']['native_query_units']+48


def test_guidance_and_cost_corruption_are_detected_without_any_dispatch(completed,tmp_path):
    directory,runner,reference,_=completed
    _,cells=reference_truth(reference.run_dir,runner.contracts)
    original=runner.run_dir/'trajectories/software-fixture-r1-LOW-WARM-CG1/TRAJECTORY_RESULT.json'
    for mode in ('guide','cost'):
        modified=copy.deepcopy(json.loads(original.read_text()))
        if mode=='guide': modified['decisions'][2]['chosen_arm']='I1_H1'
        else: modified['actual_own_physical_usage']['native_query_units']=0
        path=tmp_path/(mode+'.json');path.write_text(json.dumps(modified))
        with pytest.raises(StudyIncident): evaluate_trajectory(path,runner.contracts,cells)


def test_contract_serialization_order_does_not_change_public_feature_input_hash(completed):
    directory,runner,reference,_=completed
    _,cells=reference_truth(reference.run_dir,runner.contracts)
    reverse=Contracts(list(reversed(list(runner.contracts.specs.values()))))
    path=runner.run_dir/'trajectories/software-fixture-r1-LOW-WARM-CG1/TRAJECTORY_RESULT.json'
    checked=evaluate_trajectory(path,reverse,cells)
    assert checked['source_and_primary_receipts_independently_checked']


def test_partial_frame_is_reported_as_incomplete_not_portable_success(completed,tmp_path):
    directory,runner,reference,_=completed
    paths=list((runner.run_dir/'trajectories').glob('*/TRAJECTORY_RESULT.json'))
    summary=evaluate_campaign({'software-fixture':reference.run_dir},
        {'software-fixture':list(runner.contracts.specs.values())},paths,tmp_path/'analysis')
    assert summary['trajectory_count']==20 and not summary['complete_frozen_frame']
    assert not summary['prospective_directional_retention'] and not summary['prospective_selection_utility']
    assert summary['reference_fault_opportunity_counts']=={'software-fixture':{'1':1,'3':1}}


def synthetic_stratum(*,guided=3,combined=2,guide_queries=50,combined_queries=50,guide_discordant=0):
    values=[]
    for arm in ('I0_H0','I1_H0','I0_H1','I1_H1','CG1'):
        for repetition in (1,2):
            detections=guided if arm=='CG1' else combined
            values.append({'application_id':'app','budget_id':'LOW','history_regime':'WARM','arm':arm,
                'repetition':repetition,'detected':detections,'missed':4-detections,
                'credited_alarms':detections,'reference_discordant_alarms':guide_discordant if arm=='CG1' else 0,
                'repair_alarms':0,'allocated_standalone_native_query_units':guide_queries if arm=='CG1' else combined_queries,
                'allocated_standalone_wall_seconds':30.,'per_episode':[
                    {'episode_index':1,'detected':1},{'episode_index':2,'detected':0},
                    {'episode_index':3,'detected':detections-1}]})
    return values


def test_retention_and_utility_are_separate_and_include_reference_discordance():
    equal=matched_strata(synthetic_stratum(guided=2,combined=2))[0]
    assert equal['directional_retention'] and not equal['strict_selection_utility_before_retention_gate']
    better=matched_strata(synthetic_stratum())[0]
    assert better['directional_retention'] and better['strict_selection_utility_before_retention_gate']
    harmful=matched_strata(synthetic_stratum(guided=3,guide_discordant=1))[0]
    assert not harmful['directional_retention']
    cheaper=matched_strata(synthetic_stratum(guided=2,combined=2,guide_queries=40))[0]
    assert cheaper['directional_retention'] and cheaper['strict_selection_utility_before_retention_gate']


def test_aggregate_gain_cannot_hide_family_specific_loss_diagnostic():
    values=synthetic_stratum(guided=3,combined=2)
    for row in values:
        row['per_episode']=[{'episode_index':1,'detected':3 if row['arm']=='CG1' else 1},
                            {'episode_index':2,'detected':0},
                            {'episode_index':3,'detected':0 if row['arm']=='CG1' else 1}]
    summary=matched_strata(values)[0]
    assert summary['directional_retention'] and summary['family_specific_losses_must_not_be_hidden_by_aggregate_gain']

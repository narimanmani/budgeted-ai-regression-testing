"""Pure synthetic receipt/criterion checks; no native/model operations."""
import json
from pathlib import Path
import pytest

from experiment.development_v8.execution.analysis import audit_block_physical, audit_raw_role, summarize
from experiment.development_v8.execution.runner import StudyIncident
from experiment.development_v8.execution.test_runner import fixture


@pytest.fixture(scope='module')
def complete_block(tmp_path_factory):
    directory=tmp_path_factory.mktemp('v8-synthetic-physical-analysis')
    runner,meter,*_=fixture(directory)
    result=runner.run()
    return runner,meter,result


def test_all568_actual_mock_raw_and_common_setup_costs_reconcile(complete_block):
    runner,meter,result=complete_block
    audit=audit_block_physical(runner.run_dir,result)
    assert audit['query_receipt_count']==568
    assert audit['actual_physical_usage']['native_query_units']==568
    assert audit['all_profile_setup_and_own_costs_independently_reconciled']


def test_native_scope_mismatch_is_rejected_by_posthoc_analysis(complete_block):
    runner,meter,result=complete_block
    raw=json.loads((meter.run_dir/'raw'/next((meter.run_dir/'raw').iterdir()).name).read_text(encoding='utf-8'))
    raw['native_output']['cohort_id']='development'
    with pytest.raises(StudyIncident):
        audit_raw_role(raw,application='software-fixture',phase=raw['phase'])


def test_complete_equal_retention_does_not_manufacture_selection_utility():
    applications={app:{'reference_cells':[{'episode_index':1,'classification':'regression'},
                                         {'episode_index':3,'classification':'regression'}]}
                  for app in ('openwebui','dify')}
    evaluations=[];raw=[]
    for app in applications:
        for budget in ('LOW','HIGH'):
            for regime in ('COLD','WARM'):
                for arm in ('I0_H0','I1_H0','I0_H1','I1_H1','CG1'):
                    for repeat in (1,2):
                        evaluations.append({'application_id':app,'budget_id':budget,'history_regime':regime,
                            'arm':arm,'repetition':repeat,'detected':2,'missed':0,'credited_alarms':2,
                            'reference_regression_cells':2,'reference_discordant_alarms':0,'repair_alarms':0,
                            'allocated_standalone_native_query_units':50,'allocated_standalone_wall_seconds':30.,
                            'per_episode':[{'episode_index':1,'detected':1},{'episode_index':2,'detected':0},
                                           {'episode_index':3,'detected':1}]})
                        raw.append({'application_id':app,'repetition':repeat,'decisions':[
                            {'episode_index':ep,'feature_receipt_sha256':'a'*64,
                             'impact_receipt':{'receipt_sha256':'b'*64}} for ep in (1,2,3)]})
    summary=summarize(applications,evaluations,raw,[])
    assert summary['trajectory_count']==80 and summary['complete_frozen_frame']
    assert summary['prospective_directional_retention']
    assert not summary['prospective_selection_utility']
    assert not summary['population_significance_or_universal_portability_claim']

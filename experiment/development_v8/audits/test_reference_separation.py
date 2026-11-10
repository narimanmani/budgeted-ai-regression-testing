from copy import deepcopy
import pytest
from experiment.development_v8.audits.check_reference_separation import compare

def frame(role):
    return {'audit_passed':True,'acquisition_role':role,'application_id':'synthetic',
        'cohort_id':'validation','prompt_candidate_id':'P0','prompt_text_sha256':'prompt','input_freeze_sha256':'freeze',
        'all_scientific_query_details':[{'state_id':'HEALTHY','task_id':'T0','pass':repeat,'primary_pass':True,
            'request_id':role+str(repeat),'provider_request_id':role+'provider'+str(repeat),
            'raw_receipt_sha256':role+'hash'+str(repeat)} for repeat in (1,2)]}

def test_separate_queries_support_finite_reference_stability():
    result=compare(frame('qualification'),frame('reference'))
    assert result['independent_receipt_ids_verified'] and result['stable_reference_cells']==1
    assert result['qualification_reference_primary_disagreements']==[]

def test_reused_receipt_or_foreign_input_scope_is_rejected():
    old=frame('qualification');new=frame('reference')
    new['all_scientific_query_details'][0]['provider_request_id']=old['all_scientific_query_details'][0]['provider_request_id']
    with pytest.raises(ValueError,match='reused'):compare(old,new)
    new=frame('reference');new['input_freeze_sha256']='different'
    with pytest.raises(ValueError,match='another'):compare(old,new)

def test_reference_disagreement_is_reported_without_discarding_observation():
    new=frame('reference');new['all_scientific_query_details'][1]['primary_pass']=False
    result=compare(frame('qualification'),new)
    assert result['stable_reference_cells']==0 and len(result['qualification_reference_primary_disagreements'])==1

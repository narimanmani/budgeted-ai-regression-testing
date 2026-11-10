import pytest
from experiment.development_v8.audits.check_admission_conditions import conditions

def frame():
    spec={'task_ids':['T0','T1','T2','T3'],
        'qualification_witnesses':{'A_BAD':'T0','B_BAD':'T1'},'unaffected_controls':['T2','T3']}
    observations=[{'state_id':state,'task_id':task,'pass':repeat,
        'primary_pass':not (state=='A_BAD' and task=='T0' or state=='B_BAD' and task=='T1')}
        for state in ('HEALTHY','A_BAD','B_BAD') for task in spec['task_ids'] for repeat in (1,2)]
    return {'audit_passed':True,'admission_passed':True,'all_scientific_query_details':observations},spec

def test_rebuilds_healthy_witness_and_control_truth_requirements():
    audit,spec=frame();result=conditions(audit,spec)
    assert result['passed'] and result['required_conditions']==20 and result['satisfied_conditions']==20

def test_same_pass_count_does_not_mask_control_and_witness_swap():
    audit,spec=frame()
    for row in audit['all_scientific_query_details']:
        if row['state_id']=='A_BAD' and row['task_id'] in ('T0','T2'):row['primary_pass']=not row['primary_pass']
    with pytest.raises(ValueError,match='outcome differs'):conditions(audit,spec)
    audit['admission_passed']=False
    assert len(conditions(audit,spec)['violated_conditions'])==4

def test_missing_witness_and_duplicate_cells_are_rejected():
    audit,spec=frame();audit['all_scientific_query_details'].pop(0)
    with pytest.raises(ValueError,match='Missing'):conditions(audit,spec)
    audit,spec=frame();audit['all_scientific_query_details'].append(audit['all_scientific_query_details'][0])
    with pytest.raises(ValueError,match='Duplicate'):conditions(audit,spec)

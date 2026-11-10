"""Pure posthoc-sensitivity tests; no application, provider or model work."""
from copy import deepcopy
import json
import pytest
from experiment.development_v8.sensitivity_instance_alignment import aligned_cells,verify_override_evidence,sha


def cells():
    return [{'episode_index':episode,'task_id':task,'classification':'preserved_correct',
             'old_state':'A_BAD' if episode==2 else 'HEALTHY',
             'new_state':{1:'A_BAD',2:'HEALTHY',3:'B_BAD'}[episode]}
            for episode in (1,2,3) for task in ('VOW01','VOW07','VOW08')]


def test_only_two_labels_change_in_the_one_observed_instance_and_input_is_preserved():
    original=cells();before=deepcopy(original);result=aligned_cells(original,'openwebui',2)
    changed=[(a['episode_index'],a['task_id'],a['classification'],b['classification']) for a,b in zip(original,result) if a!=b]
    assert changed==[(1,'VOW07','preserved_correct','regression'),(2,'VOW07','preserved_correct','repair')]
    assert original==before and next(row for row in result if row['episode_index']==3 and row['task_id']=='VOW07')['classification']=='preserved_correct'


@pytest.mark.parametrize('app,rep',[('openwebui',1),('dify',1),('dify',2)])
def test_other_application_and_repetition_labels_remain_identical(app,rep):
    original=cells();result=aligned_cells(original,app,rep)
    assert result==original and result is not original


def test_already_changed_or_missing_original_cells_cannot_be_silently_realigned():
    original=cells();original[1]['classification']='regression'
    with pytest.raises(ValueError,match='original preserved'):aligned_cells(original,'openwebui',2)
    original=[row for row in cells() if not (row['episode_index']==2 and row['task_id']=='VOW07')]
    with pytest.raises(ValueError,match='Exactly'):aligned_cells(original,'openwebui',2)


@pytest.mark.parametrize('mode',['not_passed','other_primary','other_task'])
def test_posthoc_override_requires_the_exact_completed_forensic_scope(tmp_path,mode):
    primary=tmp_path/'PRIMARY.json';primary.write_text('{}')
    receipt={'audit_passed':True,'new_native_or_provider_queries':0,'primary_evaluation_or_frozen_files_modified':False,
        'primary_evaluation_sha256':sha(primary),'unique_task_ids':['VOW07']}
    if mode=='not_passed':receipt['audit_passed']=False
    elif mode=='other_primary':receipt['primary_evaluation_sha256']='0'*64
    else:receipt['unique_task_ids']=['another-task']
    path=tmp_path/'forensic.json';path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):verify_override_evidence(path,primary,None)

"""Safety checks for final cleanup ownership; no process or native operations."""
from copy import deepcopy
import pytest
from experiment.development_v8.finalize import owned_process, completed_primary


def record():
    return {'ProcessId': 101, 'ParentProcessId': 100, 'ExecutablePath': 'C:/Python/python.exe',
            'CommandLine': 'C:/Python/python.exe C:/Study/provider_bridge.py --state-dir C:/Study/run'}


def test_exact_owned_process_and_already_closed():
    expected = {'pid': 101, 'parent': 100, 'executable': 'C:/Python/python.exe',
                'required': ['C:/Study/run', 'C:/Study/provider_bridge.py']}
    assert owned_process(record(), **expected)
    assert owned_process(None, **expected)


@pytest.mark.parametrize(('field', 'replacement'), [
    ('ProcessId', 102), ('ParentProcessId', 999), ('ExecutablePath', 'C:/Other/python.exe'),
    ('CommandLine', 'C:/Python/python.exe C:/Other/provider_bridge.py --state-dir C:/Other/run'),
])
def test_reused_or_foreign_process_is_rejected(field, replacement):
    actual = deepcopy(record()); actual[field] = replacement
    assert not owned_process(actual, pid=101, parent=100, executable='C:/Python/python.exe',
                             required=['C:/Study/run', 'C:/Study/provider_bridge.py'])


def test_cleanup_cannot_accept_missing_primary_evidence(tmp_path):
    with pytest.raises(FileNotFoundError):
        completed_primary(tmp_path)


def test_registered_diagnostic_blocks_cleanup_between_stages(tmp_path):
    import json
    for app, rep in (('openwebui', 1), ('dify', 1), ('openwebui', 2), ('dify', 2)):
        path = tmp_path/f'main-{app}-r{rep}/DRIVER_COMPLETION.json'
        path.parent.mkdir(); path.write_text(json.dumps({'success': True, 'error': None}))
    evaluation = tmp_path/'evaluation/SUMMARY.json'; evaluation.parent.mkdir()
    evaluation.write_text(json.dumps({'complete_frozen_frame': True, 'trajectory_count': 80}))
    registration = tmp_path/'SECONDARY_RETESTALL_REGISTRATION.json'
    registration.write_text(json.dumps({'block_order': [{'output_dir': str(tmp_path/'secondary-missing')}]}))
    with pytest.raises(FileNotFoundError):
        completed_primary(tmp_path)

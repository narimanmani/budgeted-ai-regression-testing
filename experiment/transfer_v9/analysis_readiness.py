"""Post-execution evidence gate. This dispatches no application/model work."""
from pathlib import Path
import argparse
import subprocess

from experiment.transfer_v9.common import ROOT, HERE, read, save, sha, utc, verify_freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    for name in ('STUDY_FREEZE.json', 'ENGINEERING_AMENDMENT_FREEZE.json', 'RASA_DEPENDENCY_AMENDMENT_FREEZE.json'):
        verify_freeze(run/name)
    audit_path = HERE/'audits/INDEPENDENT_COMPLETED_VALIDATION_PY312.json'
    audit = read(audit_path)
    if audit['status'] != 'PASS_COMPLETED_STAGE_INTEGRITY' or not audit['complete_registered_frame']:
        raise RuntimeError('Completed independent validation audit is required')
    for relative, expected in audit['evidence_bindings'].items():
        path = ROOT/relative
        if sha(path) != expected:
            raise RuntimeError('Audited native evidence changed: '+relative)
    if (run/'accounting/WRITER_LOCK.json').exists():
        raise RuntimeError('The native ledger still has an active writer')
    active = subprocess.run(['docker', 'ps', '--filter', 'name=tosem-v9-rasa', '--format', '{{.Names}}'],
                            capture_output=True, text=True, check=True).stdout.strip()
    if active:
        raise RuntimeError('Owned native containers are still active')
    closed = sorted(run.rglob('CLOSED.json'))
    for path in closed:
        row = read(path)
        code = row.get('returncode', row.get('process_returncode'))
        if code is None:
            raise RuntimeError('A recorded model/native process closure is incomplete')
    resources = read(run/'VALIDATION_RESOURCE_SUMMARY.json')
    if resources['unsettled_operation_ids'] or resources['over_cap_dimensions']:
        raise RuntimeError('Unresolved or over-budget native resource work')
    summary = read(run/'evaluation/SUMMARY.json')
    if summary['bank_sha256'] != sha(run/'NATIVE_BANK.json') or summary['protocol_sha256'] != sha(run/'PROTOCOL.json'):
        raise RuntimeError('Counterfactual analysis does not match the audited bank/protocol')
    closure = {'at_utc': utc(), 'all_owned_helpers_closed': True, 'active_owned_container_names': [],
        'closed_receipt_files_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in closed},
        'unrelated_processes_or_containers_stopped': False,
        'generation_or_application_requests_during_this_check': 0}
    save(run/'OWNED_CLOSURE_CHECK.json', closure)
    files = [audit_path, run/'evaluation/SUMMARY.json', run/'PROTOCOL.json', run/'NATIVE_BANK.json',
             run/'FRESH_CONFIRMATION.json', run/'LIVE_POLICY_CONFIRMATION.json',
             run/'VALIDATION_RESOURCE_SUMMARY.json', run/'OWNED_CLOSURE_CHECK.json']
    save(run/'ANALYSIS_READINESS.json', {'status': 'PASS', 'at_utc': utc(),
        'all_owned_helpers_closed': True,
        'bound_files_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
        'integrity_does_not_establish_effectiveness_or_portability': True})


if __name__ == '__main__':
    main()

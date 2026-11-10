"""Read-only final accounting and exact-owned-process cleanup for the v8 run.

This helper is outside the scientific freeze. It never dispatches model/native
queries, removes storage, or stops containers. The frozen runtimes own their
container cleanup; this helper verifies that their recorded IDs are stopped.
"""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import math
import subprocess
import time

from experiment.development_v8.control import canonical, read, sha, write_new
from experiment.development_v8.execution.runner import utc


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def settled(run):
    if (run/'ROOT_DISPATCH_LOCK.json').exists():
        raise RuntimeError('A native dispatcher is still active')
    if read(run/'provider/ACTIVE_ALLOCATION.json')['allocation_id'] != 'CLOSED':
        raise RuntimeError('The provider allocation is still active')
    for name in ('ACCOUNTING_BLOCK.json', 'MAIN_BUDGET_STOP.json'):
        if (run/name).exists():
            raise RuntimeError('Unresolved incident: '+name)


def completed_primary(run):
    for app, rep in (('openwebui', 1), ('dify', 1), ('openwebui', 2), ('dify', 2)):
        result = read(run/f'main-{app}-r{rep}/DRIVER_COMPLETION.json')
        if result.get('success') is not True or result.get('error') is not None:
            raise RuntimeError('Primary execution is not complete')
    summary = read(run/'evaluation/SUMMARY.json')
    if summary.get('complete_frozen_frame') is not True or summary.get('trajectory_count') != 80:
        raise RuntimeError('The full primary comparison has not been evaluated')
    registration = run/'SECONDARY_RETESTALL_REGISTRATION.json'
    if registration.exists():
        for slot in read(registration)['block_order']:
            completion = read(Path(slot['output_dir'])/'SECONDARY_COMPLETION.json')
            if (completion.get('complete') is not True or completion.get('success') is not True
                    or completion.get('error') is not None or completion.get('native_queries') != 48
                    or completion.get('completed_pairs') != 24
                    or completion.get('registration_sha256') != sha(registration)):
                raise RuntimeError('The separately declared diagnostic has not fully closed')


def audit(run):
    settled(run)
    completed_primary(run)
    authority = read(run/'CAMPAIGN_AUTH.json')
    prior = read(run.parent/'validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json')
    if sha(run.parent/'validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json') != authority['prior_cost_record_sha256']:
        raise RuntimeError('Prior finalized receipt changed')
    ledger = rows(run/'native_reservations.jsonl')
    previous = '0'*64
    reservations = {}
    for index, entry in enumerate(ledger, 1):
        body = {key: value for key, value in entry.items() if key != 'sha256'}
        if (entry['index'] != index or entry['previous_sha256'] != previous
                or hashlib.sha256(canonical(body)).hexdigest() != entry['sha256']
                or entry['campaign_auth_sha256'] != sha(run/'CAMPAIGN_AUTH.json')
                or entry['global_native_query_units_after'] != prior['native_units_cumulative']+index
                or entry['request_id'] in reservations):
            raise RuntimeError('Native reservation chain/identity/carry-forward differs')
        previous = entry['sha256']; reservations[entry['request_id']] = entry
    if read(run/'NATIVE_HEAD.json') != {'index': len(ledger), 'sha256': previous}:
        raise RuntimeError('Native head differs')
    provider = rows(run/'provider/requests.jsonl')
    provider_ids = {entry['request_id'] for entry in provider}
    if len(provider_ids) != len(provider):
        raise RuntimeError('Duplicate provider request identity')
    joined = []
    operations = {}
    for entry in rows(run/'operation_index.jsonl'):
        receipt = read(entry['path']); ident = entry['allocation_id']
        if sha(entry['path']) != entry['sha256'] or receipt['allocation_id'] != ident or ident in operations:
            raise RuntimeError('Root sealed operation binding differs')
        if receipt.get('dispatch_safe_to_continue') is not True:
            raise RuntimeError('A root operation is not reconciled')
        operations[ident] = receipt
        joined.extend(receipt['provider_join'].get('provider_request_ids', []))
    boundary_ids = {entry['request_id'] for entry in provider
                    if entry['path'] in ('/v1/chat/completions', '/v1/embeddings')}
    if len(joined) != len(set(joined)) or set(joined) != boundary_ids:
        raise RuntimeError('Provider boundaries are missing or duplicated in root joins')
    for ident, entry in reservations.items():
        if operations.get(ident, {}).get('native_reservation') != entry:
            raise RuntimeError('Native reservation lacks its exact root receipt')
    counter = read(run/'provider/COUNTER.json')
    chats = [entry for entry in provider if entry['path'] == '/v1/chat/completions']
    embeddings = [entry for entry in provider if entry['path'] == '/v1/embeddings']
    measured = sum(entry.get('generate_gpu_allocation_seconds_including_failure', 0) for entry in chats)
    measured += sum(entry.get('model_setup_gpu_allocation_seconds', 0) for entry in provider)
    if (len(chats) != counter['chat_requests_reserved']
            or len(embeddings) != counter['embedding_requests_started']
            or not math.isclose(measured, counter['gpu_allocation_seconds_accounted'], abs_tol=1e-5)):
        raise RuntimeError('Provider counts or startup-inclusive allocation differ')
    native_total = prior['native_units_cumulative'] + len(ledger)
    allocation_total = prior['cumulative_generation_allocation_seconds'] + measured
    if native_total > 5000 or allocation_total > 43200 or len(ledger) > authority['native_query_cap']:
        raise RuntimeError('Shared resource envelope exceeded')
    return {'phase': 'EXTERNAL_V8', 'at_utc': utc(), 'passed': True,
            'new_native_units': len(ledger), 'prior_native_units': prior['native_units_cumulative'],
            'native_units_cumulative': native_total,
            'phase_native_counts': dict(Counter(entry['metadata']['phase'] for entry in ledger)),
            'provider_chat_boundaries': len(chats), 'provider_embedding_boundaries': len(embeddings),
            'root_operations': len(operations), 'native_chain_and_all_provider_joins_verified': True,
            'generation_allocation_seconds_this_phase': measured,
            'prior_generation_allocation_seconds': prior['cumulative_generation_allocation_seconds'],
            'cumulative_generation_allocation_seconds': allocation_total,
            'counter_sha256': sha(run/'provider/COUNTER.json'), 'native_head_sha256': sha(run/'NATIVE_HEAD.json'),
            'helper_source_sha256': sha(Path(__file__)), 'new_native_or_provider_queries': 0}


def command(argv):
    return subprocess.check_output(argv, text=True, encoding='utf-8', errors='strict',
                                   creationflags=subprocess.CREATE_NO_WINDOW).strip()


def process_record(pid):
    script = (f'Get-CimInstance Win32_Process -Filter "ProcessId = {int(pid)}" | '
              'Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress')
    value = command(['powershell', '-NoProfile', '-NonInteractive', '-Command', script])
    return json.loads(value) if value else None


def owned_process(record, *, pid, required, parent=None, executable=None):
    if record is None:
        return True
    line = (record.get('CommandLine') or '').casefold()
    return (record['ProcessId'] == pid and all(str(value).casefold() in line for value in required)
            and (parent is None or record['ParentProcessId'] == parent)
            and (executable is None or (record.get('ExecutablePath') or '').casefold() == str(executable).casefold()))


def stopped_native_containers(run):
    identifiers = set()
    for path in run.rglob('CLEANUP.json'):
        receipt = read(path).get('native_cleanup', {})
        identifiers.update(receipt.get('containers_stopped', []))
        identifiers.update(row['container_id'] for row in receipt.get('stopped', []) if isinstance(row, dict))
    results = []
    for ident in sorted(identifiers):
        result = json.loads(command(['docker', 'inspect', '--format',
            '{{json .State}}', ident]))
        if result['Running']:
            raise RuntimeError('Recorded owned native container remains active: '+ident)
        results.append({'container_id': ident, 'running': False})
    return results


def cleanup(run, final_audit):
    settled(run)
    completed_primary(run)
    if (sha(run/'provider/COUNTER.json') != final_audit['counter_sha256']
            or sha(run/'NATIVE_HEAD.json') != final_audit['native_head_sha256']):
        raise RuntimeError('Work occurred after the final accounting audit')
    native = stopped_native_containers(run)
    launch = read(run/'PROVIDER_START.json')
    child = read(run/'provider/REFERENCE_BRIDGE_OWNER.json')
    backend = read(run/'backend/START_RECEIPT.json')
    targets = [(child['pid'], [str(run), 'provider_bridge.py'], launch['pid'], None),
               (launch['pid'], [str(run), 'provider_bridge.py'], None, launch['command'][0]),
               (backend['pid'], [str(run/'backend'), '--port 33002', '--model'], None, backend['command'][0])]
    snapshots = []
    for pid, required, parent, executable in targets:
        record = process_record(pid)
        if not owned_process(record, pid=pid, required=required, parent=parent, executable=executable):
            raise RuntimeError('Refusing to stop a process with changed ownership: '+str(pid))
        snapshots.append({'pid': pid, 'record_before': record, 'required': required,
                          'expected_parent': parent, 'expected_executable': executable})
    for target in snapshots:
        pid = target['pid']; record = process_record(pid)
        if not owned_process(record, pid=pid, required=target['required'],
                             parent=target['expected_parent'], executable=target['expected_executable']):
            raise RuntimeError('Helper ownership changed immediately before cleanup')
        if record is not None:
            command(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                     f'Stop-Process -Id {int(pid)} -ErrorAction Stop'])
        deadline = time.monotonic()+10
        while process_record(pid) is not None:
            if time.monotonic() > deadline:
                raise RuntimeError('Owned helper did not exit: '+str(pid))
            time.sleep(.2)
        target['closed'] = True
    if sha(run/'provider/COUNTER.json') != final_audit['counter_sha256']:
        raise RuntimeError('Provider work changed during cleanup')
    return {'phase': 'EXTERNAL_V8', 'at_utc': utc(), 'all_owned_helpers_closed': True,
            'owned_helper_processes': snapshots, 'verified_stopped_native_containers': native,
            'counter_sha256_before_and_after': final_audit['counter_sha256'],
            'unrelated_processes_stopped': False, 'storage_or_images_deleted': False,
            'new_native_or_provider_queries': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--mode', choices=('audit', 'cleanup'), required=True)
    args = parser.parse_args(); run = args.run.resolve()
    if args.mode == 'audit':
        result = audit(run); output = run/'CAMPAIGN_FINAL_AUDIT.json'
    else:
        result = cleanup(run, read(run/'CAMPAIGN_FINAL_AUDIT.json')); output = run/'OWNED_HELPERS_CLEANUP.json'
    write_new(output, result)
    print(json.dumps({'output': str(output), 'passed': True}))


if __name__ == '__main__':
    main()

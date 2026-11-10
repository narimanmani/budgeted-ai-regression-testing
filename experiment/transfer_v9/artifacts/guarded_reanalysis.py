"""Fresh-process isolation wrapper for the actual extracted artifact check.

Copy this script outside the original workspace, then run with Python3.12 -I -B.
Only the extraction and separate reanalysis output may be accessed beneath the
original workspace. Ancestor-directory metadata is allowed for Path.resolve;
listing/opening original evidence is denied. Network/process launches are denied.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-root', required=True)
    parser.add_argument('--extraction', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('The verified audit requires Python3.12')
    abspath, normcase, fspath = os.path.abspath, os.path.normcase, os.fspath
    def normalize(value):
        return normcase(abspath(os.fsdecode(fspath(value)))).rstrip('\\/')
    original, extraction, output = map(normalize, (args.original_root, args.extraction, args.output))
    allowed = (extraction, output)
    def beneath(value, parent):
        return value == parent or value.startswith(parent + os.sep)
    if not beneath(extraction, original) or not beneath(output, original) or beneath(output, extraction):
        raise ValueError('Expected separate extraction/output subtrees under the original workspace')
    os.chdir(extraction)
    sys.dont_write_bytecode = True
    denied, ancestor_metadata = [], Counter()
    def check_path(path, operation, metadata=False):
        if isinstance(path, int) or path is None:
            return
        try:
            value = normalize(path)
        except TypeError:
            return
        if not beneath(value, original) or any(beneath(value, scope) for scope in allowed):
            return
        if metadata and any(beneath(scope, value) for scope in allowed):
            ancestor_metadata[operation] += 1
            return
        denied.append({'operation': operation, 'path': value})
        raise PermissionError('Original-workspace evidence access is blocked: ' + operation)
    def wrap_path(function, operation, metadata=False):
        def wrapped(path, *pos, **kwargs):
            check_path(path, operation, metadata)
            return function(path, *pos, **kwargs)
        return wrapped
    import builtins
    import io
    builtins.open = wrap_path(builtins.open, 'open')
    io.open = wrap_path(io.open, 'io.open')
    for name in ('open', 'listdir', 'scandir', 'stat', 'lstat', 'readlink', 'chdir'):
        if hasattr(os, name):
            setattr(os, name, wrap_path(getattr(os, name), 'os.' + name, name in ('stat', 'lstat', 'readlink')))
    def deny_execution(*pos, **kwargs):
        denied.append({'operation': 'subprocess_or_network', 'detail': 'blocked'})
        raise PermissionError('No subprocess/network dispatch is allowed during saved-data reanalysis')
    for name in ('Popen', 'run', 'call', 'check_call', 'check_output'):
        setattr(subprocess, name, deny_execution)
    for name in ('system', 'popen', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe',
                 'execv', 'execve', 'execl', 'execle', 'execlp', 'execlpe', 'execvp', 'execvpe', 'fork', 'posix_spawn'):
        if hasattr(os, name):
            setattr(os, name, deny_execution)
    socket.socket = deny_execution
    socket.create_connection = deny_execution
    socket.getaddrinfo = deny_execution
    def audit(event, arguments):
        if event == 'open' and arguments:
            check_path(arguments[0], 'audit.open')
        elif event in ('os.listdir', 'os.scandir') and arguments:
            check_path(arguments[0], 'audit.' + event)
        elif event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'os.exec'):
            deny_execution()
    sys.addaudithook(audit)
    status, result, error = 'FAILED', None, None
    try:
        module_path = Path(extraction) / 'experiment/transfer_v9/artifacts/package.py'
        spec = importlib.util.spec_from_file_location('v9_fresh_extracted_package', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.reanalyze(extraction, output)
        status = 'PASS_GUARDED_EXTRACTED_REANALYSIS' if not denied else 'FAILED_FORBIDDEN_ACCESS_ATTEMPT'
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    receipt = {'status': status, 'python': sys.version, 'extraction': extraction, 'output': output,
               'original_workspace_root_blocked': original, 'forbidden_attempts': denied,
               'ancestor_directory_metadata_only_counts': dict(ancestor_metadata),
               'ancestor_metadata_does_not_allow_original_file_opens_or_directory_listing': True,
               'network_and_subprocess_launches_blocked': True, 'reanalysis': result, 'error': error}
    with (output_path / 'GUARDED_EXECUTION.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'status': status, 'forbidden_attempts': len(denied), 'error': error}, indent=2))
    return 0 if status.startswith('PASS') else 1


if __name__ == '__main__':
    raise SystemExit(main())

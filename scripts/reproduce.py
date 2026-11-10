"""Verify or reconstruct saved results without native/model execution.

Run with CPython3.12 and -I -B. Use download_evidence.py first. Immutable v8
and v9 extractions stay separate; all new reports go to a new output directory.
The guard is an observable independence check, not an adversarial OS sandbox.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import traceback

sys.dont_write_bytecode = True


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def precheck_tree(downloader, archive_path, extraction, study):
    """Check every extracted byte before importing any extracted code."""
    names = downloader.checked_inventory(archive_path, study)
    paths = list(extraction.rglob("*"))
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in paths):
        raise ValueError("Evidence extraction cannot contain links or junctions")
    actual = {p.relative_to(extraction).as_posix() for p in paths if p.is_file()}
    if actual != set(names):
        raise ValueError("Use a clean extraction; unexpected or missing files were found")
    import zipfile
    with zipfile.ZipFile(archive_path) as archive:
        for name in names:
            expected = hashlib.sha256(archive.read(name)).digest()
            if bytes.fromhex(downloader.sha256(extraction.joinpath(*name.split("/")))) != expected:
                raise ValueError("Extracted bytes differ from the pinned archive: " + name)
    return len(names)


def install_guard(extraction, output, script_dir):
    abspath, normcase, fsdecode, fspath = os.path.abspath, os.path.normcase, os.fsdecode, os.fspath
    def norm(value):
        return normcase(abspath(fsdecode(fspath(value)))).rstrip("\\/")
    def beneath(value, root):
        return value == root or value.startswith(root + os.sep)
    allowed_reads = {norm(extraction), norm(output), norm(script_dir), norm(sys.base_prefix), norm(sys.prefix)}
    for key in ("stdlib", "platstdlib"):
        allowed_reads.add(norm(sysconfig.get_path(key)))
    output_scope = norm(output)
    denied, ancestors = [], Counter()
    def check(path, operation, *, metadata=False, writing=False):
        if isinstance(path, int) or path is None:
            return
        try:
            value = norm(path)
        except TypeError:
            return
        permitted = {output_scope} if writing else allowed_reads
        if any(beneath(value, root) for root in permitted):
            return
        if metadata and not writing and any(beneath(root, value) for root in allowed_reads):
            ancestors[operation] += 1
            return
        denied.append({"operation": operation, "path": value})
        raise PermissionError("Offline evidence guard blocked external file access: " + operation)
    def wrap_metadata(function, name):
        def wrapped(path, *args, **kwargs):
            check(path, name, metadata=True)
            return function(path, *args, **kwargs)
        return wrapped
    for name in ("stat", "lstat", "readlink"):
        if hasattr(os, name):
            setattr(os, name, wrap_metadata(getattr(os, name), "os." + name))
    def deny_execution(*args, **kwargs):
        denied.append({"operation": "network_or_process_launch"})
        raise PermissionError("Offline evidence guard blocks network and process launches")
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        setattr(subprocess, name, deny_execution)
    for name in ("system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "execv", "execve", "execl", "execle", "execlp", "execlpe", "execvp", "execvpe", "fork", "posix_spawn"):
        if hasattr(os, name):
            setattr(os, name, deny_execution)
    socket.socket = socket.create_connection = socket.getaddrinfo = deny_execution
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
    def audit(event, args):
        if event == "open" and args:
            mode, flags = args[1:3]
            writing = bool(isinstance(flags, int) and flags & write_flags) or (isinstance(mode, str) and any(c in mode for c in "wax+"))
            check(args[0], "open", writing=writing)
        elif event in ("os.listdir", "os.scandir", "os.chdir") and args:
            check(args[0], event)
        elif event in ("os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate") and args:
            check(args[0], event, writing=True)
        elif event in ("os.rename", "os.link", "os.symlink") and len(args) >= 2:
            check(args[0], event, writing=True)
            check(args[1], event, writing=True)
        elif event.startswith("socket.") or event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.exec"):
            deny_execution()
    sys.addaudithook(audit)
    return denied, ancestors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", choices=["v8", "v9"], required=True)
    repository = Path(__file__).resolve().parents[1]
    parser.add_argument("--archives-dir", type=Path, default=repository / "downloads" / "archives", help="Directory containing the original pinned ZIPs")
    parser.add_argument("--extract-dir", type=Path, default=repository / "extracted", help="Parent of separate immutable v8/v9 extractions")
    parser.add_argument("--output", type=Path, required=True, help="New directory outside immutable evidence extraction")
    parser.add_argument("--verify-only", action="store_true", help="Verify evidence bindings without reconstructing policy results")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or not sys.flags.isolated:
        raise RuntimeError("Use CPython3.12 with: python -I -B scripts/reproduce.py ...")
    script_dir = Path(__file__).resolve().parent
    downloader = load_module("release_evidence_download", script_dir / "download_evidence.py")
    archives = args.archives_dir.resolve()
    extracts = args.extract_dir.resolve()
    extraction = (extracts / args.study).resolve()
    output = args.output.resolve()
    if not extraction.is_dir():
        raise FileNotFoundError("Run scripts/download_evidence.py first; no study extraction found")
    if output == extracts or output.is_relative_to(extracts) or extraction.is_relative_to(output) or output == archives or output.is_relative_to(archives):
        raise ValueError("Reports must be outside the immutable extractions and archive directories and their ancestors")
    if output.exists():
        raise FileExistsError("Use a new output directory; existing reports will not be overwritten")
    archive_path = archives / downloader.ARCHIVES[args.study][0]
    verified_files = precheck_tree(downloader, archive_path, extraction, args.study)
    output.mkdir(parents=True, exist_ok=False)
    os.chdir(extraction)
    denied, ancestors = install_guard(extraction, output, script_dir)
    result, error, status = None, None, "FAILED"
    try:
        package_path = extraction / ("experiment/development_v8/package.py" if args.study == "v8" else "experiment/transfer_v9/artifacts/package.py")
        package = load_module("sealed_" + args.study + "_package", package_path)
        if args.verify_only:
            checked = package.verify_tree(extraction)
            if args.study == "v8":
                manifest, _, bindings = checked
                result = {"public_files_verified": len(manifest["files"]), "frozen_file_bindings_verified": bindings}
            else:
                result = {key: value for key, value in checked.items() if key != "manifest"}
        elif args.study == "v8":
            result = package.reanalyse(extraction)
        else:
            result = package.reanalyze(extraction, output / "analysis")
        status = "PASS_OFFLINE_EVIDENCE_VERIFICATION" if args.verify_only else "PASS_GUARDED_SAVED_DATA_REANALYSIS"
        if denied:
            status = "FAILED_FORBIDDEN_ACCESS_ATTEMPT"
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    receipt = {"status": status, "study": args.study, "at_utc": datetime.now(timezone.utc).isoformat(),
               "python": sys.version, "isolated_python": bool(sys.flags.isolated), "verify_only": args.verify_only,
               "archive_sha256": downloader.ARCHIVES[args.study][1], "pinned_archive_and_extracted_files_verified_before_code_import": verified_files,
               "evidence_extraction": str(extraction), "new_output_directory": str(output),
               "network_and_process_launches_blocked": True, "file_reads_restricted_to_extraction_scripts_python_runtime_and_output": True,
               "writes_restricted_to_new_output_directory": True, "forbidden_attempts": denied,
               "ancestor_directory_metadata_only_counts": dict(ancestors), "new_native_or_model_calls": 0,
               "scope": "Saved-data reconstruction; not native reexecution or independent validation of reference requirements.",
               "result": result, "error": error}
    (output / "REPRODUCIBILITY_REPORT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "study": args.study, "report": str(output / "REPRODUCIBILITY_REPORT.json"), "forbidden_attempts": len(denied), "error": error}, indent=2))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())

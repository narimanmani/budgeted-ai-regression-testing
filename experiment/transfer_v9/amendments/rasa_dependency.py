"""Install one pinned missing pure-Python dependency in a read-only mount.

No native task, model training, generation, image build or publication occurs.
Setup installation and full native-module import preflight are paid in the
original phase ledger. Original source, image and scientific inputs stay intact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
import tomllib
from urllib.request import urlopen

from experiment.transfer_v9.common import HERE, ROOT, PRIOR, read, save, sha, digest, verify_freeze, utc
from experiment.transfer_v9.runtime.ledger import Ledger, zeros

IMAGE = "rasa/rasa@sha256:a48a3523e70997282c4ab8fd86bd4702f29178a840bcfd6b673b21704f731652"
PIN = "f3b733a0c1f1ba9a9b20cac806648dbff2c5d467"
ENV_DIR = HERE / "amendments/rasa_env"
DEPS_PATH = "/study/experiment/transfer_v9/amendments/rasa_env/pydeps"
MODULES = [
    "telebot", "rasa", "rasa.engine.graph", "rasa.engine.storage.resource",
    "rasa.engine.storage.local_model_storage", "rasa.shared.nlu.training_data.message",
    "rasa.shared.nlu.training_data.training_data", "rasa.nlu.tokenizers.whitespace_tokenizer",
    "rasa.nlu.featurizers.sparse_featurizer.count_vectors_featurizer",
    "rasa.nlu.classifiers.logistic_regression_classifier", "rasa.core.actions.action",
    "rasa.core.actions.forms", "rasa.core.actions.loops", "rasa.core.channels.channel",
    "rasa.core.nlg", "rasa.shared.core.domain", "rasa.shared.core.events",
    "rasa.shared.core.trackers",
]


def _docker_base(name, *, deps_writable=False):
    command = ["docker", "run", "--rm", "--name", name, "--network", "none",
        "--read-only", "--cpus", "2", "--memory", "4g", "--tmpfs", "/tmp:rw,size=512m",
        "--mount", f"type=bind,source={ROOT},target=/study,readonly"]
    if deps_writable:
        command += ["--mount", f"type=bind,source={ENV_DIR / 'pydeps'},target=/deps"]
    for key, value in {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "RASA_TELEMETRY_ENABLED": "false", "CUDA_VISIBLE_DEVICES": "-1", "TF_CPP_MIN_LOG_LEVEL": "3",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "HOME": "/tmp", "XDG_CACHE_HOME": "/tmp/cache", "MPLCONFIGDIR": "/tmp/matplotlib"}.items():
        command += ["--env", f"{key}={value}"]
    return command


def _run(command, name, stem, timeout):
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        # Stop only the exact unique container name this helper owns.
        subprocess.run(["docker", "stop", "--time", "5", name], capture_output=True,
            timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raise
    (ENV_DIR / (stem + "_STDOUT.txt")).write_text(result.stdout, encoding="utf-8")
    (ENV_DIR / (stem + "_STDERR.txt")).write_text(result.stderr, encoding="utf-8")
    save(ENV_DIR / (stem + "_PROCESS.json"), {"command": command, "container_name": name,
        "returncode": result.returncode, "elapsed_seconds": time.perf_counter() - started,
        "auto_removed_after_exit": True, "only_owned_container": True,
        "native_task_queries": 0, "model_training_calls": 0, "provider_boundaries": 0})
    return result


def installed_manifest():
    return {path.relative_to(ENV_DIR / "pydeps").as_posix(): {"sha256": sha(path), "bytes": path.stat().st_size}
            for path in sorted((ENV_DIR / "pydeps").rglob("*")) if path.is_file()}


def verify_dependency():
    receipt = read(ENV_DIR / "DEPENDENCY_RECEIPT.json")
    manifest = read(ENV_DIR / "INSTALLED_MANIFEST.json")
    if receipt["installed_manifest_sha256"] != sha(ENV_DIR / "INSTALLED_MANIFEST.json"):
        raise RuntimeError("Dependency manifest changed")
    if manifest["files"] != installed_manifest():
        raise RuntimeError("Mounted pure-Python dependency bytes changed")
    if receipt["import_probe_sha256"] != sha(ENV_DIR / "IMPORT_PROBE.json"):
        raise RuntimeError("Full native import preflight receipt changed")
    if not read(ENV_DIR / "IMPORT_PROBE.json")["passed"]:
        raise RuntimeError("Full native imports were not qualified")
    return receipt


def command_shim(original_builder):
    """Wrap an unchanged pinned-image argument builder; no command is launched."""
    def build(**kwargs):
        verify_dependency()
        command = original_builder(**kwargs)
        if IMAGE not in command or "--entrypoint" not in command:
            raise RuntimeError("The dependency shim accepts only the original content-pinned image command")
        if any(str(value).startswith("PYTHONPATH=") for value in command):
            raise RuntimeError("Unexpected pre-existing PYTHONPATH in native command")
        insertion = command.index("--entrypoint")
        return command[:insertion] + ["--env", "PYTHONPATH=" + DEPS_PATH] + command[insertion:]
    return build


def prepare(run):
    run = Path(run).resolve()
    verify_freeze(run / "STUDY_FREEZE.json")
    verify_freeze(run / "ENGINEERING_AMENDMENT_FREEZE.json")
    failed_setup = read(run / "engineering_retry2/development/rasa-workers/H/SETUP.json")["receipt"]
    if failed_setup.get("exception_type") != "ModuleNotFoundError" or "telebot" not in failed_setup.get("message", ""):
        raise RuntimeError("This setup addition is limited to the recorded missing telebot dependency")
    if list((run / "engineering_retry2/development/raw").glob("*rasa*.json")):
        raise RuntimeError("The declared dependency repair must precede every native Rasa task output")
    if (ENV_DIR / "DEPENDENCY_RECEIPT.json").exists():
        raise RuntimeError("Never rerun or overwrite a completed dependency preparation")
    ENV_DIR.mkdir(exist_ok=False, parents=True)
    (ENV_DIR / "pydeps").mkdir()
    (ENV_DIR / "downloads").mkdir()
    lock_path = HERE / f"upstream/rasa-{PIN}/poetry.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    package = next(row for row in lock["package"] if row["name"].lower() == "pytelegrambotapi")
    if package["version"] != "4.7.0":
        raise RuntimeError("The source lock does not pin the declared dependency version")
    locked_artifacts = lock.get("metadata", {}).get("files", {}).get("pytelegrambotapi", [])
    save(ENV_DIR / "PLAN.json", {"at_utc": utc(), "package": "pyTelegramBotAPI", "version": "4.7.0",
        "source_lock_path": lock_path.relative_to(ROOT).as_posix(), "source_lock_sha256": sha(lock_path),
        "lock_artifact_hashes": locked_artifacts, "lock_pins_version_but_has_no_artifact_hash": not bool(locked_artifacts),
        "pypi_metadata_url": "https://pypi.org/pypi/pyTelegramBotAPI/4.7.0/json",
        "original_image": IMAGE, "image_changed": False, "no_dependency_resolution": True,
        "mounted_pythonpath": DEPS_PATH, "pure_import_modules": MODULES,
        "native_task_queries": 0, "model_training_calls": 0, "provider_boundaries": 0,
        "scientific_source_data_prompts_checkers_or_guidance_changed": False})
    operation = "rasa-telebot-dependency-install-and-import-preflight"
    with Ledger(run / "accounting", run / "RESOURCE_MANIFEST.json", PRIOR) as ledger:
        ledger.reserve(operation, "setup", {**zeros(), "end_to_end_seconds": 900},
            {"package": "pyTelegramBotAPI==4.7.0", "plan_sha256": sha(ENV_DIR / "PLAN.json"),
             "source_only_import_preflight": True, "no_native_tasks_or_model_training": True})
        started = time.perf_counter()
        try:
            with urlopen("https://pypi.org/pypi/pyTelegramBotAPI/4.7.0/json", timeout=30) as response:
                metadata = json.load(response)
            save(ENV_DIR / "PYPI_METADATA.json", metadata)
            artifacts = [row for row in metadata["urls"] if row["filename"].endswith("-py3-none-any.whl")]
            if not artifacts:
                artifacts = [row for row in metadata["urls"] if row["packagetype"] == "sdist"]
            if len(artifacts) != 1:
                raise RuntimeError("Expected exactly one official pure-Python wheel or source distribution")
            artifact = artifacts[0]
            if not artifact["url"].startswith("https://files.pythonhosted.org/"):
                raise RuntimeError("Dependency artifact is outside official PyPI file hosting")
            package_path = ENV_DIR / "downloads" / artifact["filename"]
            with urlopen(artifact["url"], timeout=45) as response, package_path.open("xb") as stream:
                stream.write(response.read())
            if sha(package_path) != artifact["digests"]["sha256"] or package_path.stat().st_size != artifact["size"]:
                raise RuntimeError("Official PyPI artifact hash or size mismatch")
            save(ENV_DIR / "PACKAGE_SOURCE.json", {"package": metadata["info"]["name"], "version": metadata["info"]["version"],
                "filename": artifact["filename"], "url": artifact["url"], "sha256": sha(package_path),
                "bytes": package_path.stat().st_size, "version_verified_against_source_lock": True,
                "artifact_hash_verified_against_pypi": True, "artifact_hash_not_present_in_source_lock": not bool(locked_artifacts)})
            name = "tosem-v9-rasa-dependency-install"
            command = _docker_base(name, deps_writable=True) + ["--entrypoint", "python", IMAGE,
                "-m", "pip", "install", "--no-deps", "--no-compile", "--no-cache-dir", "--disable-pip-version-check",
                "--no-build-isolation", "--target", "/deps", "/study/" + package_path.relative_to(ROOT).as_posix()]
            installed = _run(command, name, "INSTALL", 300)
            if installed.returncode:
                raise RuntimeError("Pinned dependency installation failed; preserved logs must be inspected")
            manifest = installed_manifest()
            if not manifest or not (ENV_DIR / "pydeps/telebot/__init__.py").exists():
                raise RuntimeError("Installed dependency does not supply the required telebot package")
            save(ENV_DIR / "INSTALLED_MANIFEST.json", {"package": "pyTelegramBotAPI", "version": "4.7.0", "files": manifest,
                "provider_boundaries": 0, "source_only_dependency_environment": True})
            probe_source = (
                "import importlib, json, sys, traceback\n"
                f"sys.path.insert(0, '/study/experiment/transfer_v9/upstream/rasa-{PIN}')\n"
                f"modules = {MODULES!r}\n"
                "origins = {}\n"
                "try:\n"
                "    for name in modules:\n"
                "        module = importlib.import_module(name)\n"
                "        origins[name] = getattr(module, '__file__', None)\n"
                "    from importlib.metadata import version\n"
                "    result = {'passed': True, 'origins': origins, 'pyTelegramBotAPI_version': version('pyTelegramBotAPI'), 'native_tasks': 0, 'model_training_calls': 0, 'provider_boundaries': 0}\n"
                "except BaseException as exc:\n"
                "    result = {'passed': False, 'origins': origins, 'exception_type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc(), 'native_tasks': 0, 'model_training_calls': 0, 'provider_boundaries': 0}\n"
                "print('IMPORT_PREFLIGHT_JSON=' + json.dumps(result, sort_keys=True))\n"
                "sys.exit(0 if result['passed'] else 2)\n")
            (ENV_DIR / "import_probe.py").write_text(probe_source, encoding="utf-8")
            name = "tosem-v9-rasa-dependency-import-probe"
            command = _docker_base(name) + ["--env", "PYTHONPATH=" + DEPS_PATH,
                "--entrypoint", "python", IMAGE, "/study/experiment/transfer_v9/amendments/rasa_env/import_probe.py"]
            probed = _run(command, name, "PROBE", 300)
            lines = [line for line in probed.stdout.splitlines() if line.startswith("IMPORT_PREFLIGHT_JSON=")]
            if len(lines) != 1:
                raise RuntimeError("Full native import preflight did not return one structured result")
            probe = json.loads(lines[0].split("=", 1)[1])
            save(ENV_DIR / "IMPORT_PROBE.json", probe)
            if probed.returncode or not probe["passed"] or probe["pyTelegramBotAPI_version"] != "4.7.0":
                raise RuntimeError("Full native import preflight failed; no native task is authorized")
            if manifest != installed_manifest():
                raise RuntimeError("Import-only probe changed installed dependency bytes")
            receipt = {"at_utc": utc(), "package": "pyTelegramBotAPI", "version": "4.7.0",
                "original_image": IMAGE, "image_changed": False,
                "package_source_sha256": sha(ENV_DIR / "PACKAGE_SOURCE.json"),
                "installed_manifest_sha256": sha(ENV_DIR / "INSTALLED_MANIFEST.json"),
                "import_probe_sha256": sha(ENV_DIR / "IMPORT_PROBE.json"),
                "source_lock_sha256": sha(lock_path), "mounted_pythonpath": DEPS_PATH,
                "dependency_commitment_sha256": digest(manifest),
                "source_only_import_probe_passed": True, "owned_install_and_probe_processes_closed": True,
                "native_task_queries": 0, "model_training_calls": 0, "provider_boundaries": 0,
                "complete_setup_wall_seconds": time.perf_counter() - started,
                "original_failures_and_same_phase_caps_retained": True}
            save(ENV_DIR / "DEPENDENCY_RECEIPT.json", receipt)
            ledger.settle(operation, {**zeros(), "end_to_end_seconds": time.perf_counter() - started},
                status="completed", evidence={"dependency_receipt_sha256": sha(ENV_DIR / "DEPENDENCY_RECEIPT.json")})
            return receipt
        except BaseException as exc:
            save(ENV_DIR / "PREPARATION_STOP.json", {"at_utc": utc(), "exception_type": type(exc).__name__,
                "message": str(exc), "setup_elapsed_seconds": time.perf_counter() - started,
                "native_task_queries": 0, "model_training_calls": 0, "provider_boundaries": 0})
            ledger.settle(operation, {**zeros(), "end_to_end_seconds": time.perf_counter() - started},
                status="failed", evidence={"preparation_stop_sha256": sha(ENV_DIR / "PREPARATION_STOP.json")})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.run), indent=2))


if __name__ == "__main__":
    main()

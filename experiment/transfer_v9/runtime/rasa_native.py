"""CPU-native Rasa production-path driver; imports no Rasa until explicitly run.

The dialogue path starts from parsed entity events. The NLU path actually
trains CountVectors + LogisticRegression and predicts from raw message text.
Neither path calls a generative provider. Source authority is checked before
imports; exact historical modules are selected by an import finder, not edited.
JSONL streaming permits setup/training to be measured once and reused openly.
The root dispatcher owns reservations, reference isolation and budget matching.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

BASE_PIN = "f3b733a0c1f1ba9a9b20cac806648dbff2c5d467"
NATIVE_SCOPE = {
    "form": "native Rasa dialogue-action engine given parsed entity events; NLU bypassed",
    "ranking": "native Rasa WhitespaceTokenizer + trained CountVectorsFeaturizer + LogisticRegressionClassifier",
}
PRODUCTION_MODULES = {
    "RASA_FORM_TRIGGER": {
        "rasa/core/actions/forms.py": "rasa.core.actions.forms",
        "rasa/core/actions/loops.py": "rasa.core.actions.loops",
    },
    "RASA_INTENT_RANKING": {
        "rasa/nlu/classifiers/logistic_regression_classifier.py":
            "rasa.nlu.classifiers.logistic_regression_classifier",
    },
}


class NativeAuthorityError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def under(root: Path, path: Path) -> Path:
    root, path = Path(root).resolve(), Path(path).resolve()
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise NativeAuthorityError("A declared source/mount escaped the study workspace") from exc


def source_authority(workspace: Path, source_root: Path, inventory_path: Path,
                     form_state: str, ranking_state: str) -> tuple[dict, dict]:
    """Read-only hash/Git-blob checks. No native application function executes."""
    workspace, source_root, inventory_path = map(Path, (workspace, source_root, inventory_path))
    under(workspace, source_root)
    under(workspace, inventory_path)
    if form_state not in {"fixed", "parent"} or ranking_state not in {"fixed", "parent"}:
        raise NativeAuthorityError("Only exact upstream parent/fixed module states are permitted")
    if source_root.name != f"rasa-{BASE_PIN}":
        raise NativeAuthorityError("Unexpected full-package source pin")
    inventory = read(inventory_path)
    cases = {case["case_id"]: case for case in inventory["case_candidates"]}
    module_paths, module_proofs = {}, {}
    states = {"RASA_FORM_TRIGGER": form_state, "RASA_INTENT_RANKING": ranking_state}
    for case_id, path_modules in PRODUCTION_MODULES.items():
        if case_id not in cases:
            raise NativeAuthorityError(f"Missing independent upstream case {case_id}")
        for public_path, module in path_modules.items():
            matches = [binding for binding in cases[case_id]["bindings"]
                       if binding["state"] == states[case_id] and binding["path"] == public_path]
            if len(matches) != 1:
                raise NativeAuthorityError("Missing/duplicate exact historical source binding")
            binding = matches[0]
            path = workspace / binding["local_path"].replace("\\", "/")
            under(workspace, path)
            data = path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
            if (len(data) != binding["bytes"] or sha(path) != binding["sha256"]
                    or blob != binding["git_blob_sha1"]):
                raise NativeAuthorityError("Exact historical source bytes no longer match the inventory")
            module_paths[module] = path.resolve()
            module_proofs[public_path] = {
                "case_id": case_id, "state": states[case_id],
                "source_commit": cases[case_id]["fix" if states[case_id] == "fixed" else "parent"],
                "sha256": binding["sha256"], "git_blob_sha1": blob,
                "local_path": under(workspace, path).as_posix(),
            }
    files = {path.relative_to(source_root).as_posix(): sha(path)
             for path in sorted((source_root / "rasa").rglob("*.py"))}
    if not files or "rasa/__init__.py" not in files:
        raise NativeAuthorityError("Full Rasa source package is missing")
    authority = {
        "base_source_commit": BASE_PIN,
        "base_source_version_file": (source_root / "rasa/version.py").read_text(encoding="utf-8"),
        "source_closure_sha256": digest(files), "source_python_file_count": len(files),
        "inventory_sha256": sha(inventory_path),
        "module_proofs": module_proofs,
        "version_scope": "full pinned Rasa package with exact historical production-module overlays; not whole historical releases",
        "generative_provider_calls": 0,
    }
    authority["authority_sha256"] = digest(authority)
    return authority, module_paths


def public_catalog(catalog_path: Path) -> dict:
    """Extract only executable inputs; contracts/provenance never enter a task call."""
    catalog = read(catalog_path)
    if catalog.get("application_id") != "rasa":
        raise NativeAuthorityError("Wrong application catalog")
    training = catalog.get("training_examples")
    if not isinstance(training, list) or not training:
        raise NativeAuthorityError("Explicit native training examples are required")
    for row in training:
        if (not isinstance(row, dict) or set(row) != {"text", "intent"}
                or not all(isinstance(value, str) and value for value in row.values())):
            raise NativeAuthorityError("Malformed native NLU training data")
    if len({row["intent"] for row in training}) < 2:
        raise NativeAuthorityError("Native logistic training requires at least two distinct public intents")
    tasks, ids = [], set()
    for task in catalog.get("tasks", []):
        ident, kind, value = task.get("task_id"), task.get("kind"), task.get("input")
        if not isinstance(ident, str) or not ident or ident in ids or kind not in NATIVE_SCOPE:
            raise NativeAuthorityError("Duplicate task or unsupported native path")
        if not isinstance(value, dict):
            raise NativeAuthorityError("Native task input is missing")
        validate_input(kind, value)
        tasks.append({"task_id": ident, "kind": kind, "input": value})
        ids.add(ident)
    if not tasks:
        raise NativeAuthorityError("Native task catalog is empty")
    return {"application_id": "rasa", "training_examples": training, "tasks": tasks,
            "catalog_sha256": sha(catalog_path)}


def validate_input(kind: str, value: dict) -> None:
    if kind == "ranking":
        if (set(value) != {"text", "ranking_length"} or not isinstance(value["text"], str)
                or not value["text"] or type(value["ranking_length"]) is not int
                or value["ranking_length"] < 0):
            raise NativeAuthorityError("Invalid native ranking task")
        return
    required = {"form_name", "slot_name", "slot_type", "entity_name", "entity_value",
                "user_text", "prefilled_value", "include_entity", "conditional_mapping", "second_slot"}
    if kind != "form" or set(value) != required:
        raise NativeAuthorityError("Invalid native form-task schema")
    for key in ("form_name", "slot_name", "entity_name", "user_text"):
        if not isinstance(value[key], str) or not value[key]:
            raise NativeAuthorityError("Native form names/text must be nonempty strings")
    if value["slot_type"] not in {"text", "float", "any"}:
        raise NativeAuthorityError("Unsupported prospective native slot type")
    for key in ("include_entity", "conditional_mapping"):
        if type(value[key]) is not bool:
            raise NativeAuthorityError("Explicit form input booleans are required")
    if value["second_slot"] is not None and not isinstance(value["second_slot"], str):
        raise NativeAuthorityError("Invalid optional second slot")
    canonical(value)


class HistoricalModuleFinder(importlib.abc.MetaPathFinder):
    def __init__(self, paths: dict):
        self.paths = paths

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.paths:
            return importlib.util.spec_from_file_location(fullname, self.paths[fullname])
        return None


class ProductionTrace:
    """Record calls into actual source files. Trace work is included in duration."""
    def __init__(self, source_root: Path, module_paths: dict):
        self.source_root = Path(source_root).resolve()
        self.aliases = {str(path.resolve()): key.replace(".", "/") + ".py"
                        for key, path in module_paths.items()}
        self.calls = set()
        self.previous = None

    def _profile(self, frame, event, arg):
        if event != "call":
            return
        filename = frame.f_code.co_filename
        if filename in self.aliases:
            public = self.aliases[filename]
        else:
            try:
                public = Path(filename).relative_to(self.source_root).as_posix()
            except (ValueError, OSError):
                return
        if public.startswith("rasa/"):
            self.calls.add((public, frame.f_code.co_name))

    def __enter__(self):
        self.previous = sys.getprofile()
        sys.setprofile(self._profile)
        return self

    def __exit__(self, *_):
        sys.setprofile(self.previous)

    def result(self) -> dict:
        return {"production_paths": sorted({path for path, _ in self.calls}),
                "production_functions": [{"path": path, "function": function}
                                         for path, function in sorted(self.calls)]}


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if hasattr(value, "item"):
        return jsonable(value.item())
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise NativeAuthorityError(f"Non-JSON native output type: {type(value).__name__}")


class NativeRasa:
    def __init__(self, *, workspace: Path, source_root: Path, inventory_path: Path,
                 catalog_path: Path, work_dir: Path, form_state: str, ranking_state: str,
                 expected_source_closure_sha256: str):
        self.workspace, self.source_root = Path(workspace).resolve(), Path(source_root).resolve()
        self.form_state, self.ranking_state = form_state, ranking_state
        self.authority, self.module_paths = source_authority(
            workspace, source_root, inventory_path, form_state, ranking_state)
        if self.authority["source_closure_sha256"] != expected_source_closure_sha256:
            raise NativeAuthorityError("Full pinned source closure differs from the prospective freeze")
        self.catalog = public_catalog(catalog_path)
        self.tasks = {task["task_id"]: task for task in self.catalog["tasks"]}
        self.seen_operation_ids = set()
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        with (self.work_dir / "NATIVE_RESOURCE_OWNER.json").open("x", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "source_authority_sha256": self.authority["authority_sha256"],
                       "catalog_sha256": self.catalog["catalog_sha256"], "opened_at_utc": utc()}, stream)
        if any(module == "rasa" or module.startswith("rasa.") for module in sys.modules):
            raise NativeAuthorityError("Native Rasa was imported before exact-source authority selection")
        self.finder = HistoricalModuleFinder(self.module_paths)
        sys.meta_path.insert(0, self.finder)
        sys.path.insert(0, str(self.source_root))
        self.setup_receipt = self._prepare()

    def _prepare(self) -> dict:
        started = time.perf_counter()
        with redirect_stdout(sys.stderr), ProductionTrace(self.source_root, self.module_paths) as trace:
            import rasa
            import numpy
            import scipy
            import sklearn
            from rasa.engine.graph import ExecutionContext, GraphSchema
            from rasa.engine.storage.resource import Resource
            from rasa.engine.storage.local_model_storage import LocalModelStorage
            from rasa.shared.nlu.training_data.message import Message
            from rasa.shared.nlu.training_data.training_data import TrainingData
            from rasa.nlu.tokenizers.whitespace_tokenizer import WhitespaceTokenizer
            from rasa.nlu.featurizers.sparse_featurizer.count_vectors_featurizer import CountVectorsFeaturizer
            from rasa.nlu.classifiers.logistic_regression_classifier import LogisticRegressionClassifier
            from rasa.core.actions.forms import FormAction
            from rasa.core.actions.loops import LoopAction

            self.Message, self.Classifier = Message, LogisticRegressionClassifier
            self.ExecutionContext, self.GraphSchema = ExecutionContext, GraphSchema
            model_dir = self.work_dir / "model_storage"
            model_dir.mkdir()
            self.storage = LocalModelStorage(model_dir)
            self.classifier_resource = Resource("native_logistic")
            self.tokenizer = WhitespaceTokenizer({
                "only_alphanum": False, "intent_tokenization_flag": False,
                "intent_split_symbol": "_",
            })
            self.featurizer = CountVectorsFeaturizer(
                config=CountVectorsFeaturizer.get_default_config(),
                resource=Resource("native_count_vectors"), model_storage=self.storage,
                execution_context=ExecutionContext(GraphSchema({}), node_name="native_count_vectors"),
            )
            training_data = TrainingData([Message(dict(row)) for row in self.catalog["training_examples"]])
            self.tokenizer.process(training_data.training_examples)
            self.featurizer.train(training_data)
            self.featurizer.process(training_data.training_examples)
            classifier = LogisticRegressionClassifier(
                config={"ranking_length": 10}, name="native_logistic",
                model_storage=self.storage, resource=self.classifier_resource,
            )
            classifier.train(training_data)
            self.training_classes = [str(value) for value in classifier.clf.classes_]
            origins = {}
            for module, expected in self.module_paths.items():
                actual = Path(sys.modules[module].__file__).resolve()
                if actual != expected or sha(actual) != sha(expected):
                    raise NativeAuthorityError("Imported native production module differs from historical binding")
                origins[module] = self.authority["module_proofs"][module.replace(".", "/") + ".py"]
            versions = {"rasa_source": getattr(rasa, "__version__", None),
                        "numpy": numpy.__version__, "scipy": scipy.__version__,
                        "scikit_learn": sklearn.__version__, "python": sys.version}
        elapsed = time.perf_counter() - started
        return {"event": "ready", "at_utc": utc(), "status": "ready",
                "source_authority": self.authority, "catalog_sha256": self.catalog["catalog_sha256"],
                "setup_and_training_seconds": elapsed,
                "duration_scope": "native imports, tokenization/featurization and actual CPU classifier training with trace; excludes outer Docker startup",
                "versions": versions, "imported_module_proofs": origins,
                "training_examples": len(self.catalog["training_examples"]),
                "trained_intent_classes": self.training_classes, "training_reused_within_process": True,
                "generative_provider_calls": 0, "trace": trace.result()}

    def _ranking(self, value: dict) -> dict:
        message = self.Message({"text": value["text"]})
        self.tokenizer.process([message])
        self.featurizer.process([message])
        classifier = self.Classifier.load(
            config={"ranking_length": value["ranking_length"]}, model_storage=self.storage,
            resource=self.classifier_resource,
            execution_context=self.ExecutionContext(self.GraphSchema({}), node_name="native_logistic"),
        )
        classifier.process([message])
        return jsonable({"intent": message.get("intent"),
                         "intent_ranking": message.get("intent_ranking"),
                         "configured_ranking_length": value["ranking_length"],
                         "trained_intent_classes": self.training_classes})

    async def _form(self, value: dict) -> dict:
        from rasa.core.actions.action import ActionExtractSlots
        from rasa.core.actions.forms import FormAction
        from rasa.core.channels.channel import CollectingOutputChannel
        from rasa.core.nlg import TemplatedNaturalLanguageGenerator
        from rasa.shared.core.domain import Domain
        from rasa.shared.core.events import ActionExecuted, UserUttered, SlotSet
        from rasa.shared.core.trackers import DialogueStateTracker

        mapping = {"type": "from_entity", "entity": value["entity_name"]}
        if value["conditional_mapping"]:
            mapping["conditions"] = [{"active_loop": value["form_name"]}]
        required = [value["slot_name"]]
        slots = {value["slot_name"]: {"type": value["slot_type"], "mappings": [mapping]}}
        if value["second_slot"]:
            required.append(value["second_slot"])
            slots[value["second_slot"]] = {"type": "text", "mappings": [{"type": "from_text",
                "conditions": [{"active_loop": value["form_name"]}]}]}
        domain = Domain.from_dict({
            "version": "3.1", "entities": [value["entity_name"]], "slots": slots,
            "forms": {value["form_name"]: {"required_slots": required}},
            "responses": {f"utter_ask_{slot}": [{"text": f"Please provide {slot}."}] for slot in required},
        })
        events = []
        if value["prefilled_value"] is not None:
            events.append(SlotSet(value["slot_name"], value["prefilled_value"]))
        events.append(ActionExecuted("action_listen"))
        entities = [{"entity": value["entity_name"], "value": value["entity_value"]}] if value["include_entity"] else []
        events.append(UserUttered(value["user_text"], entities=entities))
        tracker = DialogueStateTracker.from_events(
            sender_id="prospective-native-form-task", evts=events,
            domain=domain, slots=domain.slots,
        )
        output = CollectingOutputChannel()
        nlg = TemplatedNaturalLanguageGenerator(domain.responses)
        extraction = await ActionExtractSlots(None).run(output, nlg, tracker, domain)
        tracker.update_with_events(extraction, domain)
        form_events = await FormAction(value["form_name"], None).run(output, nlg, tracker, domain)
        tracker.update_with_events(form_events, domain)
        return jsonable({
            "slot_value": tracker.get_slot(value["slot_name"]),
            "requested_slot": tracker.get_slot("requested_slot"),
            "active_loop": tracker.active_loop_name,
            "pre_form_extraction_events": [event.as_dict() for event in extraction],
            "form_events": [event.as_dict() for event in form_events],
            "bot_messages": output.messages,
        })

    def query(self, operation_id: str, task_id: str) -> dict:
        if not isinstance(operation_id, str) or not operation_id or task_id not in self.tasks:
            raise NativeAuthorityError("Explicit operation ID and registered task required")
        if operation_id in self.seen_operation_ids:
            raise NativeAuthorityError("Native operation IDs cannot be reused, including failed attempts")
        self.seen_operation_ids.add(operation_id)
        task = self.tasks[task_id]
        started = time.perf_counter()
        trace = ProductionTrace(self.source_root, self.module_paths)
        with redirect_stdout(sys.stderr), trace:
            output = (self._ranking(task["input"]) if task["kind"] == "ranking"
                      else asyncio.run(self._form(task["input"])))
        elapsed = time.perf_counter() - started
        return {"event": "query", "operation_id": operation_id, "task_id": task_id,
                "kind": task["kind"], "status": "completed", "at_utc": utc(),
                "form_state": self.form_state, "ranking_state": self.ranking_state,
                "source_authority_sha256": self.authority["authority_sha256"],
                "catalog_sha256": self.catalog["catalog_sha256"],
                "task_input_sha256": digest(task["input"]), "native_scope": NATIVE_SCOPE[task["kind"]],
                "native_execution_seconds": elapsed,
                "duration_scope": "native per-task input construction, production execution, trace and result conversion; excludes shared setup and outer transport",
                "generative_provider_calls": 0, "output": output, "trace": trace.result()}


def docker_command(*, image: str, workspace: Path, work_dir: Path,
                   source_root: Path, inventory_path: Path, catalog_path: Path,
                   form_state: str, ranking_state: str,
                   expected_source_closure_sha256: str, container_name: str) -> list[str]:
    """Construct, do not execute, an isolated CPU-only JSONL service command."""
    if "@sha256:" not in image:
        raise NativeAuthorityError("Docker dependency image must be pinned by content digest")
    workspace = Path(workspace).resolve()
    if not container_name.startswith("tosem-v9-rasa-"):
        raise NativeAuthorityError("Native container name must be uniquely study-owned")
    def mounted(path):
        return "/study/" + under(workspace, path).as_posix()
    command = ["docker", "run", "--rm", "-i", "--name", container_name,
               "--network", "none", "--read-only", "--cpus", "2", "--memory", "4g",
               "--tmpfs", "/tmp:rw,size=512m", "--workdir", "/work",
               "--mount", f"type=bind,source={workspace},target=/study,readonly",
               "--mount", f"type=bind,source={Path(work_dir).resolve()},target=/work"]
    for key, value in {"RASA_TELEMETRY_ENABLED": "false", "TF_CPP_MIN_LOG_LEVEL": "3",
                       "CUDA_VISIBLE_DEVICES": "-1", "OMP_NUM_THREADS": "1",
                       "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                       "XDG_CONFIG_HOME": "/tmp/config", "XDG_CACHE_HOME": "/tmp/cache",
                       "MPLCONFIGDIR": "/tmp/matplotlib"}.items():
        command += ["--env", f"{key}={value}"]
    command += ["--entrypoint", "python", image,
                "/study/experiment/transfer_v9/runtime/rasa_native.py", "--workspace", "/study",
                "--source-root", mounted(source_root), "--inventory", mounted(inventory_path),
                "--catalog", mounted(catalog_path), "--work-dir", "/work",
                "--form-state", form_state, "--ranking-state", ranking_state,
                "--expected-source-closure-sha256", expected_source_closure_sha256]
    return command


def emit(value: dict) -> None:
    sys.stdout.write(canonical(value).decode("utf-8") + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--form-state", choices=("fixed", "parent"), required=True)
    parser.add_argument("--ranking-state", choices=("fixed", "parent"), required=True)
    parser.add_argument("--expected-source-closure-sha256", required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        native = NativeRasa(workspace=args.workspace, source_root=args.source_root,
            inventory_path=args.inventory, catalog_path=args.catalog, work_dir=args.work_dir,
            form_state=args.form_state, ranking_state=args.ranking_state,
            expected_source_closure_sha256=args.expected_source_closure_sha256)
        emit(native.setup_receipt)
    except BaseException as exc:
        emit({"event": "startup_error", "status": "study_incident", "at_utc": utc(),
              "duration_seconds": time.perf_counter() - started,
              "exception_type": type(exc).__name__, "message": str(exc),
              "traceback": traceback.format_exc(), "generative_provider_calls": 0})
        return 2
    for raw in sys.stdin:
        command = None
        command_started = time.perf_counter()
        try:
            command = json.loads(raw)
            if command == {"command": "close"}:
                emit({"event": "closed", "at_utc": utc(), "generative_provider_calls": 0})
                return 0
            if (not isinstance(command, dict)
                    or set(command) != {"operation_id", "task_id"}):
                raise NativeAuthorityError("JSONL query accepts registered task/operation IDs only")
            emit(native.query(command["operation_id"], command["task_id"]))
        except BaseException as exc:
            emit({"event": "query_error", "status": "study_incident", "at_utc": utc(),
                  "operation_id": command.get("operation_id") if isinstance(command, dict) else None,
                  "duration_seconds": time.perf_counter() - command_started,
                  "exception_type": type(exc).__name__, "message": str(exc),
                  "traceback": traceback.format_exc(), "generative_provider_calls": 0})
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

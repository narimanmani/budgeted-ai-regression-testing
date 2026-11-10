# Rasa native production-path adapter

`rasa_native.py` performs no application imports or execution when imported as
an ordinary Python module. Its pure source/catalog checks and Docker argument
builder can be exercised before a behavioral freeze. The root dispatcher must
reserve/account for every actual startup, training and native query.

The complete source package is pinned to upstream commit
`f3b733a0c1f1ba9a9b20cac806648dbff2c5d467` (Rasa source version 3.2.5).
The official `rasa/rasa:3.2.10-full` image is a dependency environment, to be
identified by its resolved content digest. It is not described as execution of
the whole original historical release. Before imports, an import finder selects
exact full upstream `parent` or `fixed` modules for:

- `rasa/core/actions/forms.py` and `rasa/core/actions/loops.py`, from the form
  trigger-slot extraction fix pair;
- `rasa/nlu/classifiers/logistic_regression_classifier.py`, from the intent
  ranking-length fix pair.

Every selected file is checked against its SHA-256, byte count and Git blob ID
in `screening/CASE_INVENTORY.json`. All 290 Python files in the base Rasa package
have source-closure SHA-256
`a05b457afdb74e86aa1fe8426866817915c5f43d0a0be03db593c20ca2c86f30`.
The caller must supply that prospective commitment; it is checked before any
native imports. Imported module origins are checked after setup. Source bytes
are not patched, AST-transplanted or replaced by mock implementations.

## Executed paths and scope

**Form tasks:** Construct a real native `Domain` and `DialogueStateTracker`
containing action-listen/user-entity events. Execute native
`ActionExtractSlots.run`, apply those events, execute native `FormAction.run`
(including `LoopAction`), then apply its actual events to the tracker. Return
the observed slot value, requested slot, active loop, native events and bot
messages. These tasks begin with parsed entity events, so they bypass NLU and
do not establish raw-text dialogue-agent performance.

**Ranking tasks:** Actually train native `WhitespaceTokenizer`,
`CountVectorsFeaturizer` and `LogisticRegressionClassifier` on an explicitly
registered training frame. The revised source-screening frame retains upstream
examples and adds authored intent examples to reach 12 intent classes. This
exercises the original premature truncation defect: the parent ranks only the
alphabetically first 10 classes before sorting, although its predicted winner
can belong to either of the excluded classes. Every ranking task uses the same
existing default length of 10 in both versions. Configurable lengths 1/2 are
not used to turn a newly added feature into an original-bug witness.

Per task, load the persisted real classifier, tokenize and featurize fresh text,
and execute native classification. Return the actual intent/ranking and
probabilities. The added training/query examples are a controlled authored
workload, not independently collected production data. This is a CPU
machine-learning pipeline; no generative provider, answer cache or prerecorded
prediction is used.

The task catalog is `screening/RASA_TASK_CATALOG.json`. Only task IDs, kinds,
inputs and explicit training examples enter native execution. Contracts,
affected-family labels and expected outcomes are stripped by `public_catalog`.
The adapter does not compute contract verdicts or make selection decisions.
Reference/operational checking is the root experiment's separate responsibility.

## Service API

`docker_command(...)` returns an argument array without launching anything. It
requires a content-pinned dependency image and study-owned container name. It
uses no network, a read-only source mount and root filesystem, CPU-only settings,
one native thread, a disposable `/tmp` and a distinct writable work directory.
Docker can then launch the Python JSONL service. Root must create the work
directory before launching; the driver creates an exclusive resource-owner
receipt and never silently reuses an earlier process's model storage.

The first stdout JSON line is a `ready` receipt containing source/module proofs,
dependency versions, actual training classes, setup/training duration and
production traces. Ordinary native logging is redirected to stderr.

Each subsequent stdin JSON line has exactly:

```
{"operation_id":"unique-reserved-id","task_id":"RF01"}
```

The resulting `query` line contains raw structured facts, the input hash,
source authority, both historical module states, actual native duration and
executed production paths/functions. Operation IDs are never reused. An
exception produces a `study_incident` record and exits the service; it must not
be counted as a product regression. Close with `{"command":"close"}`.

The process supports four explicit source combinations:
`fixed/fixed`, `parent/fixed`, `fixed/parent`, `parent/parent`. The study must
register exactly which states it intends to execute, not probe combinations
until desired outcomes appear.

## Costs and interpretation

The setup receipt covers native imports, actual CPU training and profiling.
The query duration covers input construction, native execution, tracing and
output conversion. Both exclude outer Docker startup/transport; the root timer
must include those separately. Production tracing is actual `sys.setprofile`
call tracing and its overhead is included in the durations. No timing is a GPU
kernel measure or uninstrumented production-service benchmark.

Reusing the trained model within one openly identified resource is distinct
from reusing a query output. Standalone strategy allocations must charge an
appropriate share of setup/model construction under a reuse rule fixed before
outcomes; physical setup is charged once. Native query-free checks are counted
separately from generated-answer queries.

Ten source/input/Docker construction checks cover this driver:

```
python -B -m unittest experiment.transfer_v9.runtime.test_rasa_native -v
```

These tests do not execute the application and do not establish enrollment,
fault manifestation, guidance effectiveness or untouched-application validation.

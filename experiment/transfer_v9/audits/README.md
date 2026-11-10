# Independent closed-stage checks

`audit_native.py` is a new analysis derivative outside the frozen acquisition
core. It imports only Python standard-library modules. It does not import the
collector, native adapters, recorded reference checker, ledger writer or replay
implementation, and performs no native/model/provider dispatch. For the fresh
live extension it hash-verifies and imports the original pure CG1 decision
module to recheck the recorded choice using independently reconstructed public
OLD features. That module performs no native or provider operation.

Run it with **Python 3.12**, matching the frozen acquisition interpreter, only
after the requested acquisition stage closes and while the shared campaign
ledger has no active writer:

```
EXECUTION_PYTHON -B -m experiment.transfer_v9.audits.audit_native --workspace ROOT --run RUN --stage development --output NEW_AUDIT.json
```

Use `--stage validation` after the complete native bank and fresh confirmation
close. The output file is created exclusively, preserving earlier audit records.
An audit failure is recorded as `AUDIT_FAILED` with a nonzero exit code. A
recorded study stop can be checked for retained evidence, but is never labeled
a complete frame. Source changes needed to repair a faulty auditor must remain
separate from acquisition code/data; preserve any consequential earlier audit
version and failure record.

The stored method-AST commitment uses Python 3.12's `ast.dump` representation.
The Windows default Python 3.13 produced a representation mismatch during the
first completed-development audit. Running the identical auditor under the
frozen Python 3.12.14 verified all method commitments and joins. Both audit
outputs are retained; no source, scientific record or experiment was changed.
The independent full-file SHA-256 and Git-blob checks are additionally verified.

The declared missing-`requests` engineering retry uses an explicit separately
frozen amendment, `engineering_retry2` child directory and `retry2-` native IDs.
The audit verifies that only operation namespaces and the declared dependency
environment changed, checks the same scientific admission conditions, and
retains the original paid native failure and model startup in the original
ledger. It does not relabel the original stopped attempt as successful. The
additional failed attempt raises the maximum physical attempt count to 377
under the unchanged 400-component-request envelope. Original pre-provider
failure evidence and its audit remain separate.

The second engineering addition installs the original source lock's missing
`pyTelegramBotAPI==4.7.0` as a read-only pure-Python dependency on the same pinned
image. The installed bytes, official PyPI artifact hash, complete import-only
preflight and paid setup allocation are independently checked. The source lock
pins the version but supplies no artifact hash. Completed Vanna observations
remain in `engineering_retry2`; only the unexecuted Rasa frame continues in
`engineering_rasa3`. The audit checks that explicit mixed-root mapping, fresh
operation namespaces, unchanged scientific criteria and environment-augmented
Rasa state digests. Both original engineering incidents remain attributed.

The audit independently checks:

- All original frozen source, data and configuration bytes; old receipt and
  unchanged guidance commitments; full 290-file Rasa source closure.
- Raw/frame/native reservation/settlement identities, native query versus
  query-free accounting, hash-chain/head integrity, immutable caps, attempts,
  unresolved reservations, reservation overshoots and cumulative prior costs.
- Actual SDK request/response files, model/seed/cache/output settings, zero SDK
  retries, native parent IDs, three-call ceiling, completed response hashes and
  generation durations. An independent backend log count of actual generation
  starts checks for work omitted from the SDK/normalized tables.
- Exact historical Vanna method file and AST commitments, resolved exclusively
  through registered case/version bindings. Captured absolute source paths are
  never followed. Native dependency tokens are checked against recorded calls.
- Native CPU setup/image/network isolation, actual imported historical modules,
  public catalog and actual trained intent classes; task input and resource
  authority joins; owned backend and CPU worker closure.
- SQL reference values recomputed in a separate in-memory database, duplicate
  rows and label/value associations, returned Plotly data grounding, native form
  slot/loop contracts and ranking clauses. The collector's checker is not called.
- The four fresh live cells, including complete 24-query OLD profiles for CG1,
  zero profiles for full retesting, sealed choices, fresh paired endpoints,
  predecision hashes bound in each native reservation before dispatch, the
  shared 28-request ceiling and every observed contract transition.
- Exclusive native/checker/feature timing components, nested model durations,
  setup allocations and normalized bank/raw joins. The complete frame contains
  32 development, 192 primary and 64 fresh confirmation observations, plus at
  most 88 separately registered live observations (376 maximum). Fresh receipt
  identities must be unique and retain their original outputs.

Passing these checks establishes evidence integrity within the declared
component boundary. It does not establish independent industrial cases,
population oracle accuracy, complete application-level validation, guidance
superiority or TOSEM readiness. Instrumented resource allocations are distinct
from deployment throughput, GPU utilization, energy and rental expense.

The software tests use synthetic fixtures and independent in-memory reference
SQL only:

```
python -B -m unittest experiment.transfer_v9.audits.test_audit_native -v
```

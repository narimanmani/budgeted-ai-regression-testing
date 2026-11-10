# Normalized native observation input

The replay consumes JSON with `schema_version: "v9-native-bank-1"`, a `settings`
list and a `records` list. Additional provenance fields may be retained. The
primary bank has exactly 192 records; the separate same-case confirmation bank
has exactly 64 new records. Source/raw/native/provider joins are the collector's
responsibility and need an independent receipt audit. Structural validation
alone cannot establish that a recorded request occurred.

Each setting contains:

```json
{
  "setting_id": "vanna",
  "task_ids": ["V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08"],
  "common_setup_seconds": 0.0,
  "case_ids": {"A": "VANNA_SQL_WITHIN", "B": "VANNA_ASK_FIGURE"},
  "states": {
    "H": {"state_digest": "64_HEX_CHARACTERS", "changed_tokens": []},
    "A": {"state_digest": "64_HEX_CHARACTERS", "changed_tokens": ["code:src/vanna/base/base.py/extract_sql"]},
    "B": {"state_digest": "64_HEX_CHARACTERS", "changed_tokens": ["code:src/vanna/base/base.py/ask"]}
  }
}
```

The snippet describes syntax, not executable data or evidence. Each exact-state
digest covers code, inputs and configuration sufficient to justify reuse of
three old-state samples across a return to that state. H has the same digest in
both historical case banks only if the actual fixed runtime and workload are
the same. A and B are distinct controlled historical interventions over H; the
three state digests must be distinct. Changed tokens are declared production
function/module paths with CG1-supported namespaces. Observed dependencies are
collected from actual old execution and may be empty; they are not assigned
from known failing-task labels.

Each primary record contains:

```json
{
  "record_id": "unique_operation_identity",
  "setting_id": "vanna",
  "case_id": "VANNA_SQL_WITHIN",
  "state": "H",
  "task_id": "V01",
  "pass_index": 0,
  "contract_pass": true,
  "elapsed_seconds": 0.01,
  "checker_seconds": 0.0001,
  "feature_seconds": 0.0001,
  "observed_dependency_tokens": ["code:src/vanna/base/base.py/extract_sql"],
  "raw_sha256": "64_HEX_CHARACTERS",
  "receipt_sha256": "64_HEX_CHARACTERS"
}
```

Primary passes are 0,1,2. Each historical pair executes all eight tasks in H and
its own A or B state. The two H banks contain independently executed requests,
not duplicated receipts. The frozen feature estimator takes the three A-case
H samples in pass order when H is reused. Its inputs contain durations, observed
paths and receipt IDs only, excluding contract truth and raw answers. Its
three-sample costs are not recalibrated after a method sees a favorable outcome.

`elapsed_seconds` is the exclusive native query duration: application work,
transport, SQL copy/connection or other per-query setup already inside that
duration must not be added a second time. `checker_seconds` and `feature_seconds`
are exclusive additional components. `common_setup_seconds` is a measured shared
startup/import/training allocation outside those per-query durations, charged
once to a standalone policy trajectory. The primary matched budget is native
request count; wall allocation is reported and is not wall-budget matching.
The replay additionally measures pure decision/feedback CPU and operational-mask
CPU separately. They are excluded from literal wall allocation and added only
to the explicitly named native-wall-plus-controller-CPU hybrid proxy. Controller
wall time is not measured. CPU measurements and the hybrid proxy vary on
reanalysis and must not be interpreted as native runtime, complete actual wall
time or causal production speedup. The separately registered four fresh native
policy-confirmation cells are executed by the native collector, not this replay.

The separate confirmation bank uses `pass_index: 3`, new record IDs and new
native operation receipts. It uses the same task/state cells and does not
replace primary contract outcomes. Run the stability diagnostic with:

```powershell
python -B experiment/transfer_v9/design/replay.py --bank PRIMARY_BANK.json --protocol FROZEN_PROTOCOL.json --confirmation CONFIRMATION_BANK.json --output NEW_REPLAY_OUTPUT_DIRECTORY
```

Outputs include every trajectory, matched-cell CSV, CG1 comparisons, fixed-arm
impact-by-history contrasts, checker moderation and the same-case stability
diagnostic. Zero native/model calls occur in this command. Reusing recorded
outcomes for future policy decisions and charging their hypothetical demand is
explicit counterfactual replay, not live native execution of those decisions.

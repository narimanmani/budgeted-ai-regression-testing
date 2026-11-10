# Runtime and resource review — 1 November 2026

This is a read-only feasibility review and new accounting implementation. No
application query, model generation, provider startup, native case execution or
scientific outcome was produced by this review.

## Existing campaign boundary

The verified historical receipt is
`experiment/runs/development_v8_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json`,
SHA-256 `c6f1612ee8ce6a72c10020007d0e73d50a4da0ff5dae9d68ca4851520f3b2004`.
It records 4,938 cumulative native-query units and 13,459.630427200318 cumulative
generation-allocation seconds, with all owned helpers closed. The historical
5,000-native-unit envelope therefore has 62 units left. It cannot cover a new
two-application interaction/cost study. The old 43,200-second envelope is a
generation-allocation measure, not a GPU-utilization measure or experiment wall
clock.

The legacy `experiment/development_v8/control.py` hard-binds the old phase,
previous 2,071-query baseline, prior receipt, provider source hash and 5,000
cumulative limit. `CAMPAIGN_AUTH.json` is also time-bound. Reusing or editing
these artifacts for a new study would break their evidentiary scope. They were
read, not edited.

The original frozen CG1 implementation still has SHA-256
`f14903ce1c0c3f73979eca11bd531df4303ee1fdb4d996baebcc58be89dc0989`.
Its API requires three measured old-query samples per task for its cost
profile. It receives only predecision public change tokens, paid old-state
impact evidence and earlier own selected paired judgments. In particular,
reference outcomes must not be used to fabricate useful or misleading history.
Controlled operational-checker errors may change the recorded operational
judgment; the fixed reference must remain hidden from the chooser.

A new prospective resource declaration is necessary for a new phase. Root has
proposed 400 native queries and 1,800 generation-allocation seconds as a
researcher-chosen planning envelope, with cumulative ceilings 5,338 and
15,259.630427200318 respectively. This review has **not created or activated**
that declaration. The values are not a claimed numerical instruction from the
user. The complete design must fit before any execution gate opens. Old caps,
counter files, failed attempts and receipts remain unchanged.

## Local machine snapshot

Read-only commands observed the following on 1 November 2026. These are a
feasibility snapshot, not reserved resources or sustained-throughput evidence.

| Resource | Observation |
|---|---|
| Operating system | Microsoft Windows 11 Pro |
| Physical memory | 66,608,840 KiB total; 13,829,356 KiB free at inspection |
| GPU | NVIDIA GeForce RTX 5060, 8,151 MiB total; 4,419 MiB free at inspection |
| C: disk | About 130 GB free at inspection |
| D: disk | About 1.44 TB free at inspection |
| Default Python | `C:/Python313/python.exe` |
| Other command tools | Docker, Git, Node and npm available |

Many unrelated Docker containers are running, including Aridnova, CloudHubs
and OpenTelemetry demo services. They were not stopped or modified. No model
or provider was launched. New applications should use namespaced ports,
containers, databases and temporary files with ownership receipts. Install
their pinned dependencies in separate environments rather than changing the
default Python or old study environments.

An 8 GiB GPU is suitable for the already used quantized local model under its
previous configuration, subject to current competing memory. That is an
engineering possibility, not a measured new-application capability. Avoid two
simultaneous model backends. Source-only and component checks can precede
generation without occupying the GPU; label them accurately.

## Recommended execution architecture

1. Freeze source pins, candidate inventory and selection procedure before
   behavioral screening. Source-only checks establish reachability and
   independently sourced mechanisms, not full application effectiveness.
2. Keep each native application adapter separate. Route every real generation
   and embedding boundary through a new provider interceptor; record hashes of
   requests, responses, model/configuration, source versions and runtime input.
3. Use a new append-only resource ledger, rooted in the exact sealed prior
   receipt. Reserve before dispatch, settle measured costs including failures,
   and independently reconcile adapter, provider and root operation identities.
4. Acquire each strategy's own operational history. Reference acquisition is a
   separate research cost and inaccessible to the scheduler. Checker-error
   treatments apply only to operational judgments via a prospectively fixed
   perturbation schedule; every unperturbed and perturbed verdict is preserved
   for later audit.
5. Separate physical accounting from standalone-strategy allocations. Charge
   every strategy for all evidence it would purchase, including profiles,
   traces, history and checker execution. Reuse an acquisition only after it
   exists and only under a frozen reuse rule. A baseline not purchasing a
   feature must not be charged for the chooser's research-only shared work.
6. Compare at matched end-to-end budgets along a fixed change sequence. Report
   detection/false-alarm curves and acquisition amortization together. Random
   order must use committed seeds. A later full-retest diagnostic is not a
   substitute for a simultaneously budget-matched baseline.

`runtime/ledger.py` is application-agnostic infrastructure. It deliberately does
not reuse or relabel old provider states. Query-free native component checks
and actual generated-answer queries have separate dimensions. Seventeen
software tests verify failures, crash reservations, overrun retention, zero
model caps, duplicate dispatch rejection, changed prior/manifest rejection,
concurrent writer rejection and torn/truncated ledger detection. Passing these
tests establishes accounting behavior only; it is not new case-study evidence.

## Remaining implementation requirements

- The new native adapters, dependency pins, generation/provider transport and
  complete costed design depend on the source-screening outcome.
- The ledger cannot detect an unlogged provider call on its own; independent
  boundary interception and joins are mandatory for generative claims.
- End-to-end measured seconds, upstream generation allocation, campaign elapsed
  wall time and GPU kernel use are different measures. The new registration
  must specify which one constrains each comparison.
- A frozen reference outcome from one native resource instance does not prove
  reference stability in another instance. Preserve instance identity and
  record mismatches rather than turning them into checker false positives.
- If all factorial cells and baselines cannot fit the prospective ceiling,
  report feasibility and choose a new design **before** observing validation
  outcomes. Do not trim unfavorable conditions, reset costs or stop on a win.

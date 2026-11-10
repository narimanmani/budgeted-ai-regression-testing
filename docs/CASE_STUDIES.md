# Case studies and executed boundaries

The main study uses four independently sourced historical upstream fixes across
Vanna and Rasa. The researchers reintroduce their faulty behavior into pinned
hosts and execute authored conformance workloads. These are controlled
historical interventions, rather than newly observed natural regressions in
four deployed systems.

## Main case inventory

| Case ID | Fix and mechanism | Actual executed path | Reference behavior |
|---|---|---|---|
| `VANNA_SQL_WITHIN` | [67f1bced](https://github.com/vanna-ai/vanna/commit/67f1bceda676ef8b5c6acea7c547ce1e5c67b96a): distinguish a real `WITH` CTE boundary from `WITHIN` inside a SQL literal | Local Qwen completion, Vanna `extract_sql`, SQLite execution | Extract and execute the intended query; compare returned values with a source-database computation |
| `VANNA_ASK_FIGURE` | [974ecedf](https://github.com/vanna-ai/vanna/commit/974ecedff596dd63c764335ba38e62402dee5e60): return a computed figure from the public `ask` result | `ask(print_results=False, visualize=True)`, generated SQL, native SQL result, generated Plotly code, actual figure and return tuple | A returned visualization exists and its data associations match the specified query result |
| `RASA_FORM_TRIGGER` | [177d411e](https://github.com/RasaHQ/rasa/commit/177d411e99a275673bab38ceec4eb37bd6cfce93): run conditional entity-to-slot extraction on the message activating a form | Native `Domain`, `DialogueStateTracker`, `FormAction`, loop activation and slot extraction over parsed entity events | Required form/slot state is established on activation |
| `RASA_INTENT_RANKING` | [f3b733a0](https://github.com/RasaHQ/rasa/commit/f3b733a0c1f1ba9a9b20cac806648dbff2c5d467): sort intent probabilities before truncating the ranking | Native tokenizer plus actually trained CountVectors/logistic classifier; 12 classes and default ranking length 10 | Returned ranking obeys the stated ordering/truncation invariants |

The exact parent/fix hashes, source paths, raw bindings and source licenses are
recorded in [the screened case inventory](../experiment/transfer_v9/screening/CASE_INVENTORY.json).
Its original screening-stage status strings are historical statements made
before runtime enrollment; the completed report and final receipts record the
subsequent execution. Do not infer a current incomplete run from an unchanged
pre-execution inventory field.

The SQL extraction case uses parent `14dd2fadda05b0abe8a2bbebf3691db69e24a6e7`;
the figure case uses `a28a443d3dd8f82340533b5682eadd28823f59ae`;
the form case uses `b63715a73b941dc5655a1c2ba02c958825add695`;
the ranking case uses `825539fc95a049c5962d63c1050e2b5e237a26a9`.
For every case, the inventory is the authority for the complete version pair.

## Hosts, tasks and source interventions

Vanna uses a 0.6.2 host, a complete-schema retrieval extension and exact
historical method bodies. The public figure case is the `ask` API; a Flask
figure route that does not call `ask` would not witness that specific defect.
Real generated SQL and Plotly code are executed. This native path makes no
embedding-provider calls.

Rasa's source host reports 3.2.5, while its separately pinned dependency image
is 3.2.10-full. Historical forms/loops/classifier modules are chosen before
imports. The forms begin with parsed entity events, not raw-language NLU. The
ranking path actually trains on 24 public examples across 12 classes. It does
not use a generative or embedding provider.

Each setting has eight tasks, including case-sensitive targets and controls.
Application-visible inputs exclude private reference contracts and fault-witness
annotations. Healthy H and the A/B historical-fault states recur in authored
orders. Each source fault can be revealed by multiple tasks or repeated
episodes; those opportunities remain linked to the same underlying fault.

## Execution sequence

1. Screen public fixes for concrete source semantics, public-path reachability
   and local executability, excluding applications used to develop CG1.
2. Define separate development and validation cohorts, executable contracts,
   state interventions, budgets, seed rules and outcome measures.
3. Commit the local source/data/design closure before native answers. Preserve
   the two prospective dependency amendments and original unsuccessful work.
4. Execute 32 development observations to check healthy behavior, intended fault
   witnesses and controls.
5. Acquire a 192-observation primary bank: two settings, two case pairs, two
   states, eight tasks and three passes. Execute another 64 observations for a
   fresh fourth-pass stability check.
6. Execute four fresh cold-A policy cells, totaling 88 observations including
   CG1's paid profiles. CG1 and full retesting commit decisions before dispatch.
7. Allocate recorded bank outcomes to the predeclared factorial replay:
   672 primary and 1,344 secondary trajectories, with each strategy's own history.
8. Audit source/contract/provider/budget bindings and close the campaign. Verify
   fresh archive extraction and saved-data reconstruction separately.

The local freeze is a timestamped byte commitment, not external preregistration.
The two dependency incidents concern missing host `requests` and an absent
upstream-locked `pyTelegramBotAPI` dependency. Their amendments precede all
held-out validation answers and do not change the policy, questions, contracts
or case treatments. The failed initialization remains charged.

## Supporting OpenWebUI/Dify study

The supporting study uses native OpenWebUI 0.12.5 and Dify 1.18.0 ingestion,
indexing, retrieval and Qwen generation. Its historical fault families affect
text ingestion/parsing; development and validation use distinct record IDs,
labels and source bytes while retaining task formats and those families.
Each application/cohort has eight record-to-label tasks: two A-sensitive,
two B-sensitive and four ASCII controls.

Initial development candidates P0/P1 are preserved, including failure of both
Dify candidates. A separately declared Dify P2 formatting extension is tested
on development data before held-out validation. It is not represented as
success of the original two-candidate round. The selected P0/P2 prompts, model
weights and factual judgment rule then remain fixed during validation.

All 80 primary native trajectories run under K2/K4 online pair ceilings and
cold or paid warm-history regimes. All impact admissions cover the entire
eight-task suite. Therefore this evidence concerns acquired-history ordering
and gating, not selective impact or a treatment that changes the checker.
The later full-suite diagnostic and observed-index sensitivity remain separate
from primary results. [Complete supporting report](../experiment/RESULTS_DEVELOPMENT_V8.md).

## What these cases do and do not validate

The contracts check explicit factual, execution or structural requirements.
They provide a reproducible reference for this finite comparison. Authored
contracts are not independent human validation of general requirements, and
the study does not measure free-form semantic quality, natural checker accuracy
or NLU classification accuracy. Native-path execution is not complete
historical-release or production-deployment validation. The cases provide
bounded mechanism evidence for the [reported results](RESULTS.md).

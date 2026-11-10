# Prospective independent-source case screening

This screening supplies exact upstream changes for a new study. It does not
modify the frozen CG1 policy or any completed experiment, and it has not
generated new application/model outcomes or policy scores.

The selected source candidates are Vanna's SQLite/text-to-SQL and visualization
APIs and Rasa's dialogue forms and trained intent-ranking pipeline. Both are
independently developed upstream implementations absent from the earlier
application evaluations. Their local tasks and interventions are still authored
by this study. These are candidate native-production-path case studies, not
independently operated industrial deployments or whole-system validation.

`CASE_INVENTORY.json` records four exact upstream fixes and their first parents,
the production paths, licenses/source origins, and 14 before/after file bindings
with SHA-256 and Git blob IDs. `SOURCE_ACQUISITION.json` binds complete pinned
source snapshots in `../upstream/`. Full upstream licenses remain in those
snapshots; no license is replaced by the experiment's license.

| Case | Independent source change | Contract |
|---|---|---|
| VANNA_SQL_WITHIN | `67f1bceda676ef8b5c6acea7c547ce1e5c67b96a` | SQL containing literal `WITHIN` must not be mistaken for a CTE and lose its SELECT prefix. |
| VANNA_ASK_FIGURE | `974ecedff596dd63c764335ba38e62402dee5e60` | A successfully computed figure must be returned by `ask(print_results=False, visualize=True)`. |
| RASA_FORM_TRIGGER | `177d411e99a275673bab38ceec4eb37bd6cfce93` | A form's conditional mapping can fill its slot from the triggering user message. |
| RASA_INTENT_RANKING | `f3b733a0c1f1ba9a9b20cac806648dbff2c5d467` | Intent probabilities are globally ranked, then truncated to the configured length. |

The Vanna figure fault is in the public `ask` API. The Flask figure route does
not call `ask`, so exercising that route alone cannot validate this case. Both
Vanna faults lie in `base.py`; file-level impact evidence therefore remains
broad. A selective treatment needs actual function/call evidence and its cost.

Rasa's form case has upstream event-based regression tests. It exercises native
dialogue code but bypasses NLU when supplied explicit intent/entity events.
Rasa's ranking case has an upstream regression test that runs the actual
WhitespaceTokenizer, CountVectorsFeaturizer and trained logistic classifier.
Do not describe that CPU model as an LLM. The legacy source requires Python
3.7--3.9 and old TensorFlow/scikit-learn dependencies; runtime compatibility and
the precise environment must be checked before enrollment.

`RASA_TASK_CATALOG.json` contains four form and four ranking tasks, including
two affected and two control tasks per mechanism. Operational runtime inputs
are separate from the full reference contracts. `VANNA_TASK_CATALOG.json`
contains two literal-boundary witnesses, two SQL controls, two computed-figure
witnesses and two nonvisual controls. These source-backed examples are not yet
a frozen validation cohort. The eight observations within an application do
not constitute eight independent defects.

`component_conformance.py` is an optional controlled check of exact Vanna
method bodies. Its provider/model boundary uses explicit fixtures, so its
results must remain separate from live native application evidence. It cannot
establish model reachability, application effectiveness or guidance transfer.
No native/model call occurs. An audit-only mode checks the source bindings.

Do not run either conformance or native qualification before the root agent
has frozen the applicable source/data/protocol frame. For example, after that
freeze the source audit can be written to a **new** path:

```powershell
python -B -m experiment.transfer_v9.screening.component_conformance --source-audit-only --output <new-audit-path.json>
```

The inventory preserves other screened candidates and reasons for deferral.
None was selected or rejected using CG1's effectiveness. Reverse fixed-to-parent
transitions are controlled reintroductions of independently reported historical
faults; they are not newly observed natural maintenance regressions.

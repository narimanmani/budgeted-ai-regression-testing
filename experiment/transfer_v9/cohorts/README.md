# Separate development and prospective validation bytes

Both cohorts are constructed before the first native/model observation. The
collector must bind these bytes, its full code/runtime closure and the final
resource protocol in the root freeze before dispatching development work.
`COHORT_MANIFEST.json` is a file commitment, not an external registration or
evidence that an application has qualified.

`development/` contains separate task identities, questions and source values.
The development Vanna database has six records with IDs 11--16; validation has
four records with IDs 1--4. All eight development result sets differ from their
validation counterparts. The `WITHIN` literal remains because it is part of the
same documented upstream fault mechanism. Changing records does not establish
a new fault family.

Rasa development uses different form names, slot values and query text. Both
cohorts use the same public twelve-intent training frame. The ranking reference
checks output invariants, including agreement between the native model's own
winner and the first ranked entry; it makes no language-understanding accuracy
claim. The form cases exercise structured native dialogue events, not a full
NLU conversation.

Public projections are explicit files:

- Vanna `vanna.datasource.json`: only `schema` and source `rows`.
- Vanna `vanna.tasks.public.json`: only task ID, family and question.
- Rasa `rasa.public.json`: application ID, public training examples, and task
  ID/kind/input. Contracts and expected affected-task labels are absent.

The two `*.private.json` catalogs retain evaluator-only factual references and
source provenance. Vanna's reference result sets are computed through separate
in-memory SQLite queries before any generation. Those calculations validate
the source fixture; they are not new native application observations or an
independent validation of open-ended answer quality.

`FRAME.json` provides fixed dispatcher rows. `FRAME_PLAN.json` explains their
structure and resource arithmetic:

- Development: per application, all eight healthy tasks, four A-state tasks
  and four B-state tasks; each bad-state group has two known witnesses and two
  controls. Total: 32 native requests.
- Primary validation: each case's healthy/buggy pair executes the complete
  eight-task application catalog three times. Total: 192 native requests.
- Fresh confirmation: every registered case/state/task executes once more,
  unconditionally registered before primary output. Total: 64 native requests.

The core frame is 288 native requests across four upstream cases. At the
expected one-SQL-call/two-call-figure shape it needs 180 Vanna chat requests;
the conservative ceiling at three chats per Vanna request is 432. Actual caps,
startup, failed attempts and any probes remain the root protocol's separate
responsibility. These are planning counts, not completed observations.

Development failure or absent native witnesses must be retained. A separately
declared development amendment may precede new development output; neither the
frozen guide nor validation task/contract bytes may be tuned from development
or policy scores. Confirmation does not create additional independent defects.

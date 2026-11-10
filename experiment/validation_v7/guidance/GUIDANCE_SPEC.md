# CG1 conditional guidance: ready for prospective freeze

Status: **new, unvalidated candidate** derived from the completed v6 development
pilot. This file does not claim a frozen rule until root records its source hash
and timestamp. No external application outcomes or fault candidates were read
while developing this rule. It has no application, task-name, fault-family or
expected-answer lookup table.

The guide chooses one of the four unmodified v6 procedures for each change:
I0_H0 (cost), I1_H0 (impact then cost), I0_H1 (global own history then cost),
I1_H1 (impact plus global own history then cost). It is not a new scoped-history
ranker: when H1 is chosen, all earlier own positive event counts are used exactly
as in v6. Its novelty within this validation is the prospective gate/choice, not
an already demonstrated contribution.

1. Use impact only if a receipt-bound, matching predecision old-state feature
   block supplies a valid nonempty strict subset of the current public catalog.
   Whole-catalog, missing-provenance or empty old-trace intersections use broad
   admission. Unknown source bindings must have remained conservatively admitted
   when the application-specific impact builder produced that subset.
2. Use global history only if there is at least one positive earlier **own,
   selected, timely, old-correct/new-incorrect** paired observation and **every**
   such positive event has a nonempty public change-token intersection with the
   current change. Any incompatible or unknown positive event disables global
   history. Cold history therefore starts with H0. Foreign, future, reference or
   unselected judgments are rejected as protocol errors, not silently learned.
3. Form the eligible I/H candidate using those gates. At the current pair ceiling
   K, choose the least complex eligible arm whose **ordered nominal K-prefix**
   equals that candidate's prefix. Complexity is the number of enabled mechanisms;
   deterministic ties prefer I0_H0, I1_H0, I0_H1, I1_H1. A rejected mechanism is
   never introduced during simplification.

Nominal prefix equality is a predecision planning heuristic. It does not prove
equal actual outputs, tail selections, or wall-time behavior under noisy costs.
The experiment primarily tests K=2/K=4 pair budgets; all actual elapsed work and
any wall safeguard overruns still count. No complete causal-impact or safe-skip
guarantee follows from a returned-context trace.

Public change tokens are namespaced, case-sensitive canonical IDs: `code:` plus
an exact repository-relative production-file path, `config:` plus a public
setting-key path, `dependency:` plus a public package ID, or `document:` plus a
stable public original-document ID. No learned family labels, gold source hints,
function identities inferred after failures, or hand-mapped cross-application
categories are allowed. Code tokens are file-granularity: different defects in
the same file may falsely appear compatible. Conversely, shared causes in
different files may appear incompatible. Those are operating limits to measure,
not reasons to change the token granularity after seeing held-out outcomes.

All five procedures receive the same paid old-state cost/context block inside an
application/repetition/old-state block. Three query costs per task produce the
fixed pair-cost estimate `2 * median(old_query_wall_seconds)`. Context evidence is
the conservative union of those three actual old observations, never answer
judgments. The A-state profile is unavailable until A has become the logical old
state of the repair episode. The guide pays its actual decision/index processing;
choosing a simple arm does not erase feature-acquisition costs already incurred.

The root runner owns native dispatch, wall guards, history provenance and receipt
joins. It records the selected arm and predecision input hash before querying the
new state. Only later selected timely primary pairs can update that trajectory's
history. Fixed baselines always use their fixed arm, including unconditional
global H1 counts; they do not borrow the guide's gate.

Call `choose(task_ids, pair_cost_seconds, impact, history, trajectory_id=...,
feature_block_id=..., episode_index=..., changed_tokens=..., pair_limit=...)` in
`policy.py`. `rank_arm` supplies the common four baseline ranking semantics. The
function is pure and performs no I/O, model call or reference-bank access.

The v6 source evidence motivating the rule is limited: all-admit TXT filtering
was redundant under common features; warm history recovered recurrence; two K2
structural settings showed novel-fault displacement; cost ranks varied. The new
compatibility gate and prefix simplification were not native v6 treatments.
External validation can support, qualify or refute CG1. Do not tune it on those
outcomes or replace it with a retrospectively better rule in the primary report.

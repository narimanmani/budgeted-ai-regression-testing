# Results and interpretation

This guide explains the completed findings and where their supporting evidence
is stored. The canonical reports are [the main Vanna/Rasa report](../experiment/RESULTS_TRANSFER_V9.md)
and [the separate OpenWebUI/Dify report](../experiment/RESULTS_DEVELOPMENT_V8.md).
They preserve unsuccessful attempts, null effects and unfavorable comparisons.

## Evidence and denominators

The main study has four historical faults in two pinned native-path settings.
It completed 376 observations: 32 development, 192 primary-bank, 64 fresh
fourth-pass and 88 live-policy observations. One failed initialization remains
charged, giving 377/400 attempts. The fourth-pass executions agree with the
three primary observations in all 64 state/task/case cells; this is stability
within the fixed frame, not a population reliability estimate.

The bank supports 672 primary 16-change trajectories and 1,344 secondary
4/8-change trajectories, with 18,816 decisions. These are allocations over
recorded outcomes. They add no independent defects or new application calls.
The 32 primary strata combine setting, order, impact condition, judgment
condition and request ceiling; each aggregates three recorded passes.

A counted main-study detection requires an old-pass/new-fail reference pair
to be selected and recognized by the operational judgment. Existing failures,
repairs and reference-discordant alarms are separate outcomes. The contracts
check SQL execution/results, returned figure data, form state and ranking
invariants. They do not measure general answer quality or NLU semantic accuracy.

## Fresh cold-start comparison

All four cells use the same 28-request ceiling, empty history and exact
judgments. CG1 pays 24 profile requests before selecting two pairs; full
retesting buys no profiles and executes all eight pairs in 16 requests.

| Setting | CG1 revealing pairs / requests | Full revealing pairs / requests |
|---|---:|---:|
| Vanna | 0 / 28 | 2 / 16 |
| Rasa | 1 / 28 | 2 / 16 |

CG1 selects Vanna controls `VC01,VC02`; in Rasa it selects affected task `RF01`
and control `RF03`. The two revealing tasks in a setting concern one A fault.
These are each method's own observed pairs, not a cross-arm recall estimate.

The cold cost inequality follows from the protocol: three old profiles per
task cost `3N`, while full old/new retesting costs `2N`. It is not a newly
discovered empirical law. The executions show which opportunities the profile
purchase leaves untested. Native/checker/feature wall allocations are 50.274
versus 36.451 seconds in Vanna and 1.611 versus 1.102 in Rasa; fixed order and
shared prepared platforms preclude a causal deployment-speedup claim.

Evidence: [live-cell CSV](../results/v9/ACTUAL_FOUR_LIVE_CONFIRMATION_CELLS.csv),
[figure](../results/v9/four_actual_native_confirmation_cells.png), and the
archive's `LIVE_POLICY_CONFIRMATION.json` with predispatch ledger commitments.

## Acquisition and recurrence

Profile-consuming methods pay 24 requests per distinct old H/A/B state and can
reuse a profile only when the state digest is identical. This creates at most
72 profile requests in the constructed recurrence. Request savings require
`3NS + 2P < 2NT`, where S is the number of acquired distinct-state profile
blocks, P is selected pairs and T is changes. Detection preservation is an
additional requirement; lower request demand alone does not establish benefit.

Under balanced interleaved order, observed edges, exact judgments and the high
allowance of 64/128/256 requests at 4/8/16 changes:

| Setting | Changes | CG1 detections | Full detections | CG1 requests | Full requests |
|---|---:|---:|---:|---:|---:|
| Rasa | 4 | 6/12 | 12/12 | 60 | 64 |
| Rasa | 8 | 21/24 | 24/24 | 128 | 128 |
| Rasa | 16 | 48/48 | 48/48 | 200 | 256 |
| Vanna | 4 | 6/12 | 12/12 | 62 | 64 |
| Vanna | 8 | 15/24 | 24/24 | 128 | 128 |
| Vanna | 16 | 48/48 | 48/48 | 240 | 256 |

Detection aggregates three passes; requests are per trajectory. The 16-change
cells preserve detection with 21.9% and 6.25% fewer requests, respectively.
Impact-only and always-combined also attain complete detection there. Shorter
CG1 prefixes miss opportunities. Repeating identical H/A/B states is an
optimistic cache-reuse scenario, not validation over continuously new versions.
Blocked 4/8-change prefixes contain A alone and are descriptive because their
case mixture differs from the full blocked sequence.

Evidence: [balanced recurrence CSV](../results/v9/BALANCED_INTERLEAVED_AMORTIZATION.csv),
[cost/detection figure](../results/v9/balanced_recurrence_cost_and_detection.png),
and [composition-confounded blocked prefixes](../results/v9/BLOCKED_PREFIX_COMPOSITION_CONFOUNDED_DESCRIPTIVE.csv).

## Impact-history interaction and judgment errors

The primary factorial frame includes observed versus deliberately omitted
impact edges, exact versus deliberately flipped operational judgments, two
orders and 128/256-request ceilings. History is acquired separately by each
strategy from its own selected pairs. The reference remains unchanged.

The additive detection contrast is `Delta_IH = D(IH)-D(I)-D(H)+D(C)`.
It is positive in 3 primary conditions, zero in 21 and negative in 8. All
positives occur in Vanna at the 128-request ceiling; all negatives occur under
flipped judgments. Matched moderation `Delta_flip-Delta_exact` decreases in
10 conditions and is unchanged in 6; it never increases in the primary frame.

| Setting | Order | Edges | Requests | Exact contrast | Flipped contrast | Moderation |
|---|---|---|---:|---:|---:|---:|
| Rasa | Blocked | Observed | 128 | 0 | -1 | -1 |
| Rasa | Blocked | Observed | 256 | 0 | -6 | -6 |
| Rasa | Blocked | Omitted | 128 | 0 | -1 | -1 |
| Rasa | Blocked | Omitted | 256 | 0 | -6 | -6 |
| Rasa | Interleaved | Observed | 128 | 0 | 0 | 0 |
| Rasa | Interleaved | Observed | 256 | 0 | -3 | -3 |
| Rasa | Interleaved | Omitted | 128 | 0 | 0 | 0 |
| Rasa | Interleaved | Omitted | 256 | 0 | -3 | -3 |
| Vanna | Blocked | Observed | 128 | 0 | 0 | 0 |
| Vanna | Blocked | Observed | 256 | 0 | 0 | 0 |
| Vanna | Blocked | Omitted | 128 | +6 | +3 | -3 |
| Vanna | Blocked | Omitted | 256 | 0 | 0 | 0 |
| Vanna | Interleaved | Observed | 128 | 0 | 0 | 0 |
| Vanna | Interleaved | Observed | 256 | 0 | -4 | -4 |
| Vanna | Interleaved | Omitted | 128 | +3 | 0 | -3 |
| Vanna | Interleaved | Omitted | 256 | 0 | -2 | -2 |

The Vanna blocked/omitted/128 example gives exact detections C=0,I=6,H=0,IH=12
and contrast +6. With flipped judgments the counts are 0,2,0,5, giving +3.
Omitting cheap controls from admission admits figure targets in that particular
mask. This does not justify discarding dependency evidence generally.

In Rasa blocked/observed/256, exact counts C=H=24,I=IH=48 yield zero contrast
despite impact's detection advantage. Flipped counts C=10,H=16,I=IH=22 yield
-6: history helps without impact but adds nothing inside impact admission.
I and IH choose identical task sets in that recorded example. A negative
interaction therefore does not by itself show that combination is inferior.
Zero contrasts can conceal floors, ceilings or different schedules with equal
counts.

The 0.25 omission/flip probability is a seeded stress parameter, not the
measured natural error rate or a guarantee of exactly 25% corruption in each
selected subset. Judgment flips affect immediate recognition and later history
together. These are finite sequential-regime contrasts, not population causal
estimates or independently sampled bugs.

Evidence: [all primary fixed-arm contrasts](../results/v9/FIXED_I_BY_H_CONTRASTS.csv),
[moderation](../results/v9/CHECKER_MODERATION_CONTRASTS.csv),
and [matched cells](../results/v9/PRIMARY_MATCHED_CELLS.csv).

## Every primary comparator

| Comparator | CG1 detection gains | Ties | Losses |
|---|---:|---:|---:|
| Budgeted catalog retesting | 0 | 17 | 15 |
| Seeded random | 2 | 15 | 15 |
| Profiled latency C | 26 | 6 | 0 |
| Impact plus latency I | 8 | 23 | 1 |
| History plus latency H | 20 | 10 | 2 |
| Always-combined IH | 1 | 30 | 1 |

Counts concern 32 analytic strata, not 32 faults. Against combined, the gain is
one repeated detection and the loss is three, giving two fewer overall.
Allocated requests are equal; CG1 additionally raises more discordant alarms
in three strata. Improvements over the profiled latency control are not
superiority over full retesting, random selection or published algorithms that
were not reproduced here.

The harmful Vanna blocked/omitted/flipped/128 condition gives CG1 2 detections
versus combined's 5, with 13 versus 11 discordant alarms. CG1 rejects useful
local history because the global history set contains another scope. Conversely,
rejecting stale figure history preserves SQL targets in a different interleaved
condition. These are post hoc explanations of frozen decisions, not newly fitted
selection rules.

Evidence: [CG1 comparisons](../results/v9/CG1_PRIMARY_COMPARISONS.csv),
[case-level differences](../results/v9/CG1_PRIMARY_CASE_COMPARISONS.csv),
and [complete comparator figure](../results/v9/primary_cg1_detection_differences.png).

## Retained background SQL failure

Vanna task `VS04` fails in all 21 checked validation observations: 12 primary,
4 fourth-pass and 5 live/profile observations. The generated CTE ends with
`SELECT total_amount;` instead of selecting from its `totals` CTE. SQLite
rejects it. Completions stop normally at 23 tokens, below the 256-token limit.
It already fails in H and persists in changed states, so false-to-false pairs
receive no newly introduced regression credit. It is one background generated
failure pattern, not 21 defects, a fifth upstream case, output truncation or a
demonstrated checker implementation error.

## Supporting native ordering study (v8)

All 80 primary native trajectories complete; all 720 selected pairs are timely.
Impact admits every task in all 12 blocks, so I=C and IH=H in selection. This
study isolates ordering/history behavior with coarse impact evidence, not a
selective-impact or operational-error treatment.

| Application | K | Initial history | C | I | H | IH | CG1 |
|---|---:|---|---:|---:|---:|---:|---:|
| OpenWebUI | 2 | Cold | 2/8 | 2/8 | 2/8 | 2/8 | 2/8 |
| OpenWebUI | 2 | Warm | 2/8 | 2/8 | 3/8 | 3/8 | 3/8 |
| OpenWebUI | 4 | Cold | 2/8 | 2/8 | 2/8 | 2/8 | 2/8 |
| OpenWebUI | 4 | Warm | 2/8 | 2/8 | 5/8 | 5/8 | 5/8 |
| Dify | 2 | Cold | 1/8 | 1/8 | 1/8 | 1/8 | 1/8 |
| Dify | 2 | Warm | 1/8 | 1/8 | 4/8 | 4/8 | 5/8 |
| Dify | 4 | Cold | 3/8 | 3/8 | 3/8 | 3/8 | 3/8 |
| Dify | 4 | Warm | 3/8 | 3/8 | 5/8 | 5/8 | 6/8 |

Each row aggregates two repetitions and eight repeated opportunities. Total
detections are C=I=16/64, H=IH=25/64 and CG1=27/64 at 1,184 allocated queries
per method across 16 trajectories. These standalone allocations must not be
summed as physical work. Actual physical primary work is 2,272 queries.

The two extra detections are Dify warm K2/repetition1 and K4/repetition2; they
do not recur at both repetitions of either budget. CG1 misses 37/64 overall
and detects fewer B-family opportunities than C (11/32 versus 14/32).

### Reference-instance format noncompliance

All 26 transition disagreements concern OpenWebUI task `VOW07` in the second
A_BAD native index. Its 39 answers contain `[TERRACE-703]` instead of the bare
label `TERRACE-703`, while the reference and first-main indexes pass. Both
checker implementations agree that the actual bracketed answer violates the
unchanged contract; this is not established erroneous checker feedback.
The correct fact reaches the model. Native resource identifiers differ, but
their causal role is unestablished.

A separate explicitly post hoc sensitivity aligns that instance's assumed
reference to its observed failures. It yields CG1=29/68 versus IH=27/68; the
original 27/64 versus 25/64 remains primary. The larger denominator repeats one
instance across treatments, adding no independent defects.

### Full-suite diagnostic and physical accounting

The later separate diagnostic detects 16/16 opportunities across four sequences,
each using 48 fresh queries. Cold selected trajectories allocate 60/72 queries
at K2/K4; warm trajectories allocate 76/88. The diagnostic exceeds the primary
online pair ceilings and runs later, so it is not a sixth matched arm or a
causal runtime experiment.

The full v8 phase consumes 2,867 native generation-oriented units: development
240, provider probes 3, qualification 64, reference 96, profiles 192, own warm
history 640, selected endpoints 1,440 and secondary full retesting 192. With
2,071 carried-forward earlier units, the campaign closes at 4,938/5,000. Its
2,864 task-generation payloads and three provider-validation probes retain
different generation settings; all costs and unsuccessful development remain.

## Scope of the overall conclusion

The evidence supports conditional acquisition/reuse and feedback-interaction
findings within small controlled native-path studies. It does not establish a
generally superior selector, full unseen-application guidance, model-replacement
performance, semantic-judge accuracy or production wall-time savings. Fresh
native executions and recorded-outcome replay answer different questions and
are never pooled as independent application replications.

# Closed-data presentation derivative

This folder is outside the frozen experimental core. Its helper does not make
native/model calls, change reference labels, edit the paper or seal the final
report. All software checks use synthetic fixtures. Do not run the helper on
current study data until root has declared validation closed and the independent
completed-validation audit has passed.

The helper itself enforces both gates before opening any result data. The
independent native audit must contain:

```json
{
  "status": "PASS_COMPLETED_STAGE_INTEGRITY",
  "stage": "validation",
  "complete_registered_frame": true,
  "native_or_provider_dispatches_during_audit": 0,
  "evidence_bindings": {"WORKSPACE_RELATIVE_PATH": "SHA256"}
}
```

Root's separate `ANALYSIS_READINESS.json` must contain:

```json
{
  "status": "PASS",
  "all_owned_helpers_closed": true,
  "bound_files_sha256": {"WORKSPACE_RELATIVE_PATH": "SHA256"}
}
```

Readiness must bind the exact independent audit, `evaluation/SUMMARY.json`,
`NATIVE_BANK.json`, `PROTOCOL.json`, `LIVE_POLICY_CONFIRMATION.json` and
`VALIDATION_RESOURCE_SUMMARY.json`. The four native inputs must also match the
independent audit bindings. The replay summary's bank/protocol digests must agree
with those native-audited inputs. Relative bindings resolve only inside the
explicit workspace. A passed derivative gate does not establish effectiveness.

Example after both gates pass:

```powershell
python -B experiment/transfer_v9/presentation/present_results.py --workspace C:/Users/narim/OneDrive/Documents/ChatGPT/TOSEM --run RUN_DIRECTORY --audit INDEPENDENT_VALIDATION_AUDIT.json --readiness RUN_DIRECTORY/ANALYSIS_READINESS.json --output RUN_DIRECTORY/presentation
```

`--summary` and `--protocol` override those two default input locations when
needed. The output directory must be new. `--no-plots` skips plotting; unavailable
Matplotlib also causes a documented plotting skip, with no dependency install.

Outputs include primary matched-cell CSVs; per-case CG1 comparison CSV; fixed
impact-by-history and checker-moderation contrasts; balanced-interleaved
amortization; a separate composition-confounded blocked-prefix table; four
actual live confirmation cells; public resource fields; scope notes and a
compact findings JSON. Static scientific SVG/PNG plots show registered primary
differences, balanced recurrence costs/detection, and actual cold-A native cell
costs. The live chart reports observed pair counts, not recall borrowed from a
different arm's native observations.

Each output is hashed in `PRESENTATION_RECEIPT.json`. Historical/native records
are read-only. Four upstream cases, 672 primary counterfactual trajectories and
four fresh cold-A native cells remain distinct units. Exact H/A/B cache reuse
over repeated versions is an optimistic recurrence setting, not evidence for
amortization over unseen new versions or full application-level portability.

Run the synthetic software checks:

```powershell
python -B -m unittest discover -s experiment/transfer_v9/presentation -p "test_*.py"
```

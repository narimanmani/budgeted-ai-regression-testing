# Public packaging and isolated saved-data reanalysis

These files are post-freeze derivative tooling. They do not change any frozen
study source, task, contract, decision, raw response or analysis rule. No command
in `package.py` starts an application, model, provider, Docker process or network
request. Do not build the real archive until the root agent has sealed the final
report and completed accounting, native audits and owned-helper cleanup.

The package includes the exact primary freeze, later prospective engineering
amendments, all named frozen public sources, original failed attempts/stopping
records, native and SDK evidence, ledger/setup/closure receipts, original frozen
guide, independent auditors, replay implementation, final report and pinned
upstream licenses. Pinned public source fixtures are retained unchanged,
including JSONC/editor configuration, public environment examples, certificates,
encrypted fixtures and source archives. They are not decrypted or treated as
user credentials. Recognized private-key/credential markers block packaging.

Complete byte checking concerns the primary v9 freeze and its engineering
amendments. Earlier-study receipts and guidance-freeze documents remain exact
historical provenance; shipping them does not claim to reproduce every earlier
dataset or reverify old unshipped model/application assets.

Python environments, user databases, SQLite/model working state, model weights,
runtime executables, Docker images and old full evidence archives are excluded.
The small exact public pyTelegramBotAPI source distribution and pure Python
source files bound by the Rasa dependency amendment are included for complete
amendment-byte verification. This narrow source inclusion does not ship a full
installed environment; the original source archive retains its license.
The archive records external asset hashes as historical commitments. It does not
claim to rehash absent bytes. Original absolute paths are retained inside raw
receipts; the native auditor resolves historical Vanna methods through the
registered case/version inventory and never reads their original locations.

Build inputs must name the completed run, reviewed report and final receipt.
The final receipt must contain a matching `report_sha256`,
`reviewed_report_sha256` or `results_report_sha256`, and
`all_owned_helpers_closed: true` or `all_helpers_closed: true`.

An audit specification is a JSON array of root-relative module/entry/run calls:

```json
[
  {
    "module": "experiment/transfer_v9/audits/audit_native.py",
    "entry": "audit_stage",
    "run": "experiment/runs/transfer_v9_20261101",
    "stage": "development"
  }
]
```

The packaged independent function receives `(extracted_workspace,
extracted_run, stage)` or `(extracted_workspace, extracted_run)` when `stage` is
absent. A combined engineering-retry auditor can therefore be supplied without
rewriting historical records or frozen source. Every requested call must return
a `PASS...` status; no closed stage should be silently omitted.

If the study reaches replay, an analysis specification identifies these exact
root-relative paths (the root agent supplies the actual completed locations):

```json
{
  "bank": "experiment/runs/transfer_v9_20261101/NATIVE_BANK.json",
  "protocol": "experiment/runs/transfer_v9_20261101/PROTOCOL.json",
  "confirmation": "experiment/runs/transfer_v9_20261101/FRESH_CONFIRMATION.json",
  "evaluation": "experiment/runs/transfer_v9_20261101/evaluation",
  "replay_module": "experiment/transfer_v9/design/replay.py",
  "guidance": "experiment/validation_v7/guidance/policy.py"
}
```

`confirmation` can be absent only if the original replay did not include it.
Omit `--analysis-spec` when retained development failure prevented replay; the
artifact then verifies that stopping record and does not manufacture results.

```powershell
python -B -m experiment.transfer_v9.artifacts.package build --root <workspace> --run <closed-run> --report <sealed-report> --final-receipt <sealed-accounting> --audit-spec <audit-spec.json> --analysis-spec <analysis-spec.json> --output <new-evidence.zip>
python -B -m experiment.transfer_v9.artifacts.package verify-zip --zip <new-evidence.zip>
python -B -m experiment.transfer_v9.artifacts.package extract --zip <new-evidence.zip> --destination <new-empty-extraction>
```

From the fresh extraction, use **Python 3.12 (tested 3.12.14)** and no installed
application dependencies. Historical method AST commitments are version scoped;
Python 3.13 is not the verified audit environment:

```powershell
python -I -B experiment/transfer_v9/artifacts/package.py verify-tree --root .
python -I -B experiment/transfer_v9/artifacts/package.py reanalyze --root . --output <new-directory-outside-extraction>
```

Reanalysis checks every manifest and frozen binding, invokes the independent
read-only auditor, recomputes all original replay trajectories, summary,
comparisons, matched-cell CSV and fresh-bank stability diagnostic. Equality
excludes only the three freshly measured replay fields declared by the frozen
core: `decision_cpu_seconds`, `operational_mask_cpu_seconds`, and
`total_allocated_native_wall_plus_controller_cpu_proxy_seconds`. Every outcome,
selection, mask, verdict, detection, alarm, request allocation, recorded native/
setup/checker/feature duration and confirmation is still compared. The original
CPU fields remain in the unchanged original files; new measurements are written
separately outside the extraction.

ZIP checks enforce safe paths, no case collisions or links, file/byte limits,
CRC and per-file SHA-256. Extraction uses a new directory; tree verification
rejects extra files and original-host fallbacks. The root agent should run a
fresh-process isolation guard that blocks subprocess/network and original
workspace access while performing the final extracted reanalysis.

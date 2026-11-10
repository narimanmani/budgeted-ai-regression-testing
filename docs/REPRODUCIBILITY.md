# Verify and reconstruct the completed results

The supported reproduction path is **offline reanalysis of saved native
observations**. It verifies preserved source/contract/budget bindings and
recomputes the registered analyses without starting native applications,
containers, models or paid providers. It does not claim to reexecute the
original application environment or to independently validate the authored
requirements.

## Choose a level of inspection

| Level | Inputs | What you can do |
|---|---|---|
| Read results | Repository README, docs, reports and `results/` | Inspect every central result and its limitations |
| Browse implementation | `experiment/` | Inspect original design, case bindings, selection/evaluation code and auditors |
| Verify and reconstruct | Complete release ZIP for each study | Check every manifest-bound file and recompute saved-data comparisons |
| Repeat native execution | Separately acquired model/runtime/images plus frozen source/configuration | Perform a separately planned experiment after environment recreation and path adaptation |

The repository keeps code and compact results browsable. Complete run logs,
observations and trajectory evidence reside in the exact release archives.
**Use each complete archive as its own evidence root**, not the repository root
or a tree assembled by mixing studies.

## Quick start with the repository helpers

Some exact upstream source paths exceed Git for Windows' default path limit.
Enable long paths for the clone without changing global Git settings:

```text
git clone -c core.longpaths=true https://github.com/narimanmani/budgeted-ai-regression-testing.git
cd budgeted-ai-regression-testing
```

If an initial Windows clone completed its download but failed during checkout,
enable `core.longpaths` in that fresh clone before retrying checkout. Do not
discard or overwrite unrelated working changes. Python extraction and Git
checkout are separate operations; keep the checkout path reasonably short.

From the cloned repository:

```text
python scripts/download_evidence.py --study all
python -I -B scripts/reproduce.py --study v9 --output reproduced/v9
python -I -B scripts/reproduce.py --study v8 --output reproduced/v8
```

The downloader saves pinned release ZIPs under `downloads/archives/` and
extracts them into separate `extracted/v9/` or `extracted/v8/` directories by
default. The reproduction wrapper checks or creates those extractions and
verifies the manifest-bound evidence bytes before importing frozen analysis
code, and writes a `REPRODUCIBILITY_REPORT.json` in the selected new output
directory. Main-study output also includes
`analysis/REANALYSIS_VERIFICATION.json` and `analysis/recomputed-replay/`.
The wrappers use no native application or model execution. They are release
conveniences added after the study; they do not replace or modify the frozen
policy, scientific analysis or original evidence.

Add `--verify-only` to a reproduction command to verify evidence without
recomputing analysis, choosing a separate new output directory, for example:

```text
python -I -B scripts/reproduce.py --study v9 --verify-only --output verified/v9
```

Both helpers accept explicit `--archives-dir` and `--extract-dir` paths as
documented by their `--help` output. The reproduction wrapper requires Python
3.12; the downloader can run on a newer supported Python interpreter. The
following manual steps expose the underlying archive commands.

## Requirements

- Python **3.12**, tested with **3.12.14**. Main-study historical method-AST
  commitments are Python-version scoped; Python 3.13 is not the verified
  audit environment.
- Enough disk space for approximately **1.35 GB** uncompressed supporting v8
  evidence and **233 MB** uncompressed main v9 evidence, plus analysis outputs.
- A download tool such as GitHub CLI, a browser or `curl` for acquiring release
  files. Verification and reanalysis themselves do not require network access.

No model weights, Docker installation, GPU, application services, API keys or
third-party native-application dependencies are needed for saved-data reanalysis.
The archive instructions are in each archive's root `ARTIFACT_README.md`.

## 1. Download the pinned release archives

- [Main v9 evidence](https://github.com/narimanmani/budgeted-ai-regression-testing/releases/download/v1.0.0/transfer_v9_evidence.zip)
- [Supporting v8 evidence](https://github.com/narimanmani/budgeted-ai-regression-testing/releases/download/v1.0.0/development_v8_evidence.zip)
- [Repository checksum list](../evidence/CHECKSUMS.sha256)

For example, from the cloned repository with an authenticated or public GitHub CLI:

```text
gh release download v1.0.0 --repo narimanmani/budgeted-ai-regression-testing --pattern transfer_v9_evidence.zip --dir downloads/archives
gh release download v1.0.0 --repo narimanmani/budgeted-ai-regression-testing --pattern development_v8_evidence.zip --dir downloads/archives
```

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `transfer_v9_evidence.zip` | 35,860,358 | `5928f3a9eabf7d846f9488a3a2c99878b62bcc2babff8d7559cc0cec7300765f` |
| `development_v8_evidence.zip` | 152,224,642 | `99e7167f3b77bb1729bca020f38aba446a79d6dcbf8227a9dfaff32afa8cfbd3` |

## 2. Verify the downloaded ZIP hashes before extraction

On PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 downloads/archives/transfer_v9_evidence.zip
Get-FileHash -Algorithm SHA256 downloads/archives/development_v8_evidence.zip
```

On a shell providing `sha256sum`:

```sh
sha256sum downloads/archives/transfer_v9_evidence.zip downloads/archives/development_v8_evidence.zip
```

Compare the complete hashes to the table above or the checksum file. The archive
tools additionally verify member paths, CRC, per-file hashes, frozen bindings
and limits; a matching ZIP hash is the first integrity check, not the entire
scientific audit.

## 3. Extract into separate new directories

Use Python 3.12 for these commands and the following steps:

```text
python --version
python -m zipfile -e downloads/archives/transfer_v9_evidence.zip extracted/v9
python -m zipfile -e downloads/archives/development_v8_evidence.zip extracted/v8
```

Use fresh empty destinations. Do not merge the two archives, rewrite old path
strings, add outputs inside the evidence roots or edit a frozen file to make a
check pass. Manifest verification rejects unexpected files or changed bytes.
Raw receipts retain historical host paths as provenance; resolvers map reads
through the included manifests instead of following original host locations.

## 4. Verify and reanalyze the main v9 study

From the cloned repository's working directory:

```text
python -I -B extracted/v9/experiment/transfer_v9/artifacts/package.py verify-tree --root extracted/v9
python -I -B extracted/v9/experiment/transfer_v9/artifacts/package.py reanalyze --root extracted/v9 --output reanalysis/v9
```

`reanalysis/v9` must be a **new directory outside the extraction**. The first
command verifies the evidence tree. The second invokes included independent
read-only auditing and recomputes the registered replay and fourth-pass stability
analysis. It compares the original trajectories, masks, selections, judgments,
detections, alarms, request allocations and recorded native/setup/checker/feature
durations.

The preserved main archive has 4,489 manifest-bound public files. Prior guarded
verification checked all 344 validation/live observations plus the separate 32
development observations, verified 1,506 primary/amendment file bindings and
reconstructed 2,020 core analysis files: 2,016 trajectories and four associated
analysis files. Original native/model executions are not repeated by this step.

Only three newly measured replay fields are excluded from deterministic equality:

- `decision_cpu_seconds`
- `operational_mask_cpu_seconds`
- `total_allocated_native_wall_plus_controller_cpu_proxy_seconds`

Their original measurements remain preserved. Fresh CPU measurements and the
derived hybrid proxy can differ on a new host; outcomes and the other recorded
costs must still agree. This is not permission to ignore other discrepancies.

## 5. Verify and reanalyse the supporting v8 study

The supporting tool spells the command `reanalyse`:

```text
python -I -B extracted/v8/experiment/development_v8/package.py verify --root extracted/v8
python -I -B extracted/v8/experiment/development_v8/package.py reanalyse --root extracted/v8
```

It returns a JSON reconstruction report. It verifies original frozen/source
bindings, native/root/provider accounting, development selection, qualification,
reference acquisition and all 80 main trajectories through unchanged extracted
policy/evaluator code. It also reconstructs the separate full-suite diagnostic
and explicitly post hoc index-instance sensitivity. The latter does not replace
the original primary reference or rescue the original criteria.

The preserved v8 archive has 18,642 manifest files and prior verification checked
402,147 immutable bindings. Its earlier campaign cost is carried forward from
the included finalized receipt, not reexecuted. Recorded timing is audited from
saved events; historical clocks are not independently remeasured.

## Expected scientific reconstruction

- Main cold cells: CG1 Vanna 0 pairs/28 requests and Rasa 1/28; full retesting
  2/16 in each setting under the same ceiling.
- Primary interaction signs: 3 positive, 21 zero, 8 negative; 10 moderation
  decreases and 6 unchanged.
- Balanced 16-change recurrence: CG1 complete repeated detection at 200 requests
  in Rasa and 240 in Vanna versus 256 for full retesting.
- CG1 versus always-combined: one gain stratum, 30 ties and one loss; net two
  fewer repeated detections in the primary frame.
- Supporting study: CG1 27/64 versus combined 25/64, at 1,184 allocated queries
  each; post hoc aligned sensitivity 29/68 versus 27/68 remains separate.

The complete [results guide](RESULTS.md) explains denominators, comparisons and
limitations. A successful reanalysis establishes consistency of this finite
preserved evidence, rather than portable effectiveness or production speedup.

## Native reexecution and omitted assets

The archives preserve design, source interventions, cohorts, contracts, commands,
versions and hashes. They exclude working private databases, model weights,
runtime executables, Docker images and full installed application environments.
Some excluded provider/package assets retain explicit hash commitments. These
are records about absent assets, not verification of their unshipped bytes.

A new native campaign requires separately obtaining those pinned assets,
constructing the documented [environment](ENVIRONMENTS.md), adapting historical
host paths and deciding a new budget/protocol. Never restart closed original
campaigns or overwrite their receipts. The present repository does not claim
that raw source alone recreates a full deployment automatically.

## Evidence integrity and release interpretation

Archive manifests, original freezes, prospective dependency amendments,
unsuccessful attempts, stopping records and closure receipts remain preserved.
Keep upstream license/notice terms with their own files. The archives' historical
README statements about then-unpublished release status remain documentary
source bytes; this GitHub release records their later distribution.

No DOI or artifact-evaluation badge follows merely from a GitHub upload. A
separate checking implementation is not an external industrial replication or
independent human validation of the chosen contracts. If a verification fails,
retain its output and identify the exact mismatch rather than changing evidence
or silently switching reference outcomes.

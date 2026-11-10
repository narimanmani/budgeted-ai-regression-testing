# Public v8 evidence artifact

The new packager preserves every public development observation, including the
closed P0/P1 failure and separately declared P2 extension; fresh qualification and
reference observations; all actual main work; and cumulative cost provenance.
It does not start applications, containers, providers, models or network calls.
Final creation is blocked until the canonical results report and closed final
accounting/cleanup receipt exist. It does not modify frozen experiment sources.
The public-file safety ceiling is 2 GiB uncompressed, with a 512 MiB individual
file limit; these archive limits are separate from the unchanged study budgets.

From the workspace, after the campaign is finalized:

```powershell
python -B experiment/development_v8/package.py plan --run-dir experiment/runs/development_v8_20261101
python -B experiment/development_v8/package.py create --run-dir experiment/runs/development_v8_20261101 --zip output/development_v8_evidence.zip
python -B experiment/development_v8/package.py verify --zip output/development_v8_evidence.zip
```

Extract the ZIP into an empty directory. From any working directory:

```powershell
python -I -B <extract>/experiment/development_v8/package.py verify --root <extract>
python -I -B <extract>/experiment/development_v8/package.py reanalyse --root <extract>
```

Reanalysis resolves historical absolute paths only through the included manifest.
It checks original freezes and native/root receipt bindings; reconciles the native
reservation chain, every provider boundary and costs; independently rechecks
development and fresh acquisition judgments; and executes unchanged extracted CG1
and evaluator source for a complete main comparison. It compares recomputed
criteria with the canonical saved summary, without trusting that summary as input.
Original receipt bytes and path strings remain intact. Timing checks audit saved
events and elapsed values; they do not independently remeasure the earlier clock.
The primary comparison remains the frozen 80 trajectories. If a separately
declared RetestAll diagnostic is present, its observations and costs remain a
separate secondary comparison; it is not an added primary arm and cannot rescue
the original retention or utility criteria.
The optional observed-index sensitivity remains explicitly post hoc. Reanalysis
checks its forensic receipt and three paid OLD native proofs, reproduces both
original and aligned 80-trajectory scores with the unchanged evaluator, and
compares the summaries separately. It does not replace primary reference truth
or constitute an alternative-oracle experiment.

Private state, credentials, databases, model/executable/image binaries, full
upstream clones, dependency builds and internal handoffs are excluded. Individual
explicitly frozen public source files remain. Public research allowance files
contain no service credentials and are included because freezes bind their caps.
The native provider `.difypkg` is excluded; its exact hash and original freeze
declaration are retained. This is a hash commitment, not verification of absent
archive bytes. Reexecuting native apps requires separately obtained dependencies.

The exact OpenWebUI and Dify root `LICENSE` files and applicable `NOTICE` or
`COPYING` files governing selected source paths are retained with their original
terms. Their checkout-byte hashes, source revision and pinned Git-object hashes
are recorded. CRLF checkout differences are disclosed without changing the
shipped bytes. Full upstream clones remain excluded. There is no umbrella
relicensing; formal license/public-release review remains an author TODO.

The installed `workloads/component_deps` tree is pruned. No study/run JSON freeze
or immutable receipt references files in that tree in this campaign. If a new
explicit frozen dependency appears, packaging fails instead of silently dropping
it. Native saved-data reanalysis does not need this tree; reproducing source-only
component projections requires separately installed pinned ftfy/chardet/wcwidth
libraries. The existing projection records and version provenance remain.

Earlier campaign costs are carried from the preserved v7 finalized receipt; the
artifact does not claim to rerun all earlier campaigns. The scope is transfer to
fresh workload instances in the same developed applications and historical fault
families. A complete comparison or a positive admission gate does not establish
unseen application generalization or universal guidance.

Offline software checks:

```powershell
python -B -m pytest -q experiment/development_v8/test_package.py
```

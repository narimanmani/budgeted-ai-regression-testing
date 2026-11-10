# Separate development and fresh validation workloads

Each cohort contains eight tasks in each of Dify and OpenWebUI. Their record
identifiers, exact labels and original bytes are disjoint from each other and
from v7's task/answer values. The native applications and historical fault
families remain the same; this is a fresh workload, not new-application or
new-bug discovery. The facts are researcher-authored controlled catalog records,
not a sampled production corpus.

Every question names a record identifier present inside the source content and
asks for its bracketed access label. It does not depend on filenames being
visible to the LLM. Primary contracts are derived from the unique bracket span
in strictly decoded original bytes; no native/generated answer supplies gold.

The Dify tasks include two labels containing U+00EF, two labels with meaningful
internal ASCII spaces and four unaffected ASCII labels. The historical cleaner
mistakenly removed U+00EF/U+00BF/U+00BE, rather than arbitrary accented letters.
Each newline-free paragraph exceeds the native 50-character chunk threshold and
keeps the complete label in its first healthy chunk. This exercises the actual
recursive ASCII-space splitter branch.

OpenWebUI has two literal HTML-entity labels in plain TXT, two CP932 Japanese
labels and four ASCII labels. Its A fix preserves literal entity spellings;
the historical A path unescapes them. Its B fix changes native encoding-hint
handling. Text encoding remains auto-detected by the application.

`GENERATION_FRAME.json` declares fixed seeds and values. `prompts.json` contains
two generic candidates, P0 then P1, with no task identity or accepted value.
Root must run both complete development candidates and select the first eligible
candidate using the frozen qualification requirements alone. No CG1 outcome is
an input to that choice. Root must then separately freeze the chosen native
configuration and the validation file hashes before any validation answers.

`WORKLOAD_FILES.json` binds generated inputs. `WORKLOAD_AUTHORITY_AUDIT.json`
records eight passing software checks and 32 source-authorized contracts.
`COMPONENT_PREFLIGHT.json` records 32 passing source sensitivity projections.
These projections use exact captured production methods and pinned versions
ftfy 6.3.1/chardet 7.4.3, outside the native application. The chardet wheel is for
Windows CPython 3.13; actual native Linux ingestion and answer qualification are
still required. No application or model calls were made here.

An initial source-only Dify draft used unaffected accents and a trailing newline
that missed the relevant splitter branch. It was rejected before native/model
outputs and preserved under `source_screening/initial_candidate`. The selected
source-sensitive revision is explicit in the authority audit.

Run the pure checks with:

```powershell
C:/Python313/python.exe -B -m pytest experiment/development_v8/workloads/test_workloads.py -q
```

The native runtime consumes only `tasks.json`/`public_tasks.json`, source bytes
and `source_manifest.json`. Contract values, descriptive mechanism partitions,
component projections and qualification outcomes must not become policy inputs.

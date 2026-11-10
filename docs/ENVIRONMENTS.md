# Recorded execution environments

This description uses retained launch commands, startup logs, native setup
receipts and manifests. It reports the environment actually recorded for the
completed runs, rather than current hardware or older asset-setup intentions.
Full hashes and command lines remain in the separate evidence archives.

## Shared local generation backend

| Item | Recorded value |
|---|---|
| Platform | Windows x86-64; exact release/build not captured |
| CPU and memory | Intel Core Ultra 5 225F; startup log reports 65,047 MiB host memory |
| GPU | NVIDIA GeForce RTX 5060; log reports 8,150 MiB device memory |
| Backend | llama.cpp build 11960, commit `8642541b2`, Clang 20.1.8 |
| Model | `Qwen/Qwen2.5-7B-Instruct-GGUF`, revision prefix `bb5d59e06d95`, two Q4_K_M GGUF shards and official Qwen chat template |
| Context and offload | 4,096 tokens, 26 GPU-offloaded layers, F16 KV offload |
| Scheduling | One parallel slot, batch 512, microbatch 128, four inference and four batch CPU threads |
| Disabled features | Context shifting, warmup and cross-request prompt reuse |

The supporting study's server ceiling is 512 output tokens, but its **2,864
actual task-generation payloads use temperature 0 and `max_tokens=96`**, without
an explicit caller seed. The three separately charged Dify provider-validation
probes request five tokens and leave temperature unspecified. This distinction
prevents the server ceiling or probe settings from being reported as the
scientific task-generation setting.

The main Vanna payloads use temperature 0, `max_tokens=256`, seed 20261101 and
`cache_prompt=false`. Its OpenAI-compatible client permits no SDK retry.
Measured generation allocation includes instrumentation and transport overhead
plus recorded startup; it is not GPU kernel time, rental cost or energy.

## Supporting OpenWebUI/Dify environments

| Item | OpenWebUI | Dify |
|---|---|---|
| Application | 0.12.5 | 1.18.0 |
| Source revision prefix | `f7ac7ee10962` | `50abea970621` |
| Image | `ghcr.io/open-webui/open-webui`, digest prefix `61b567ee1e77` | `langgenius/dify-api`, digest prefix `0120970fb4ea` |
| Container platform | Linux amd64 | Linux amd64 |
| Retrieval | Chroma, top-k 8, chunk size 1,000, overlap 100 | Native high-quality semantic retrieval, Weaviate, top-k 20; custom max_tokens 50, separator `\n\n`, overlap 0 |
| Selected prompt | P0 | Disclosed development extension P2 |

Both use normalized 384-dimensional `all-MiniLM-L6-v2` embeddings on CPU,
revision prefix `1110a243fdf4`. Hybrid search/reranking and optional query,
summary or title generation are disabled as recorded for the applications.
Dify's provider plugin and PostgreSQL, Redis and Weaviate images have their
own content pins in the archive.

Windows-side Python adapters orchestrate the containers. Exact contemporaneous
controller and application-container Python patch versions were not recorded;
the archive retains image pins and recipes instead. Native resource identifiers
differ between reference and execution indexes. They are retained runtime
outputs, not presumed byte-identical inputs.

## Main Vanna environment

The controller and Vanna host use Python 3.12.14. Recorded packages include
OpenAI SDK 1.109.1, HTTPX 0.28.1, pandas 3.0.1, NumPy 2.3.5, Plotly 5.24.1,
SQLAlchemy 2.0.36, sqlparse 0.5.3 and Flask 3.1.0. A prospective engineering
amendment supplies requests 2.32.3 and its recorded transitive additions.

Vanna 0.6.2 executes the complete-schema extension and exact historical
`extract_sql`/`ask` bodies, actual local generation, SQLite and generated
Plotly code. No embedding-provider calls are made on this path.

## Main Rasa environment

| Item | Recorded value |
|---|---|
| Source host | Rasa 3.2.5, with selected exact historical modules |
| Dependency image | `rasa/rasa:3.2.10-full`, digest prefix `a48a3523e709` |
| Interpreter/libraries | Python 3.8.10, NumPy 1.19.5, SciPy 1.7.3, scikit-learn 0.24.2 |
| Dependency amendment | Read-only PYTHONPATH addition supplying upstream-locked pyTelegramBotAPI 4.7.0 |
| Resource limits | Two CPU quota, 4 GiB memory, one OpenMP/OpenBLAS/MKL thread |
| Isolation | No network, read-only root/source mount, CUDA visibility disabled |
| Ranking training | Native tokenizer, CountVectors/logistic components, 24 public examples, 12 intent classes; persisted model loaded for per-task inference |
| Form inputs | Native trackers with parsed entity events |

Rasa makes no generative-model or embedding-provider requests. Its CPU-native
task counts remain a separate physical dimension from generative-provider calls.

## Environment information deliberately not inferred

Exact Windows release/build, Docker Desktop version and container kernel
version were not captured. Current versions cannot repair those historical
gaps. Unshipped model, executable and image hashes are documentary commitments;
the archive does not claim verification of asset bytes that it does not contain.
Obtaining those assets and adapting host-specific paths is required for a new
native experiment. The supported portable task is [offline saved-data
verification and reanalysis](REPRODUCIBILITY.md).

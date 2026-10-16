# Native CORE pilot — 2026-10-16, V235

This run uses the original public CORE bug reports against the complete original source revisions. It evaluates Ken's existing production pipeline; no engine, model weights, query text, ranking parameter or private acceptance case is changed.

## Scope and interpretation

- Three repositories: `mwaskom/seaborn`, `pallets/flask`, `psf/requests`.
- Eleven original SWE-bench Verified base revisions, one original question per revision. The existing CORE selection contains 18 level-specific cases: 11 LEVEL-2 and seven LEVEL-3. Repeated questions across levels share one native prediction per route and one latency measurement.
- 1,812 regular source files, 31,254,005 bytes across the snapshots; archives total 16,216,948 bytes. Names, extensions and bytes are preserved. Repository code and dependencies are never executed or installed.
- CORE data commit `23da5d97a8a4495d4bd6d5616aa86d5a12a60699`; source revision metadata from SWE-bench Verified commit `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`. The selected revisions and archive hashes are retained.
- Frozen engine commit `8ce6b00c3a653e2effa46ec02b7acedd4c100501`; all 425 source-manifest entries verified, manifest SHA256 `b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079`. Default production resources, CPUExecutionProvider, 1024 reranker tokens, ten result slots and 12,000 characters of evidence.
- Two fixed routes, evaluated separately for every question: `scope=symbols,piece_kind=symbol` and `scope=files,piece_kind=file`. No route is chosen from its answer. Errors remain in the denominators.

LEVEL-2 means the preexisting function/method responsible for the requested correction, independently identified from the public report and original source. LEVEL-3 means source context marked positive by CORE; an appropriate context function need not implement the requested fix. The report keeps these levels separate. Combined counts are descriptive because seven questions occur in both levels.

The source corpus and relevance units differ from the original opaque-chunk CORE protocol. These are native piece/file hit rates; they are not original CORE NDCG, a private acceptance result, or a repository-held-out generalization claim. The earlier text-adapter pilot remains a separate, unchanged result.

## Reference contract

Independent source curation located all 160 original positive occurrences literally and uniquely. All 18 original case IDs and query hashes remain present. LEVEL-2 has 12 responsible implementation alternatives for 11 cases; LEVEL-3 has 129 context alternatives for seven cases. Across them there are 100 canonical callable targets and 41 specific fragment targets.

A **file hit** requires the exact native path, current physical source SHA256 and `stale=false`. A **piece hit** additionally requires either the exact canonical function/method kind, complete qualname and definition end (start may vary only inside the source-verified decorator-to-definition interval), or a complete specific reference anchor in one faithful returned code excerpt. A containing file, class or unrelated member alone earns no piece credit. Exact callable identity deliberately does not require an additional visible-body gate. Fragment references have no whole-container identity shortcut. Adjacent excerpts are not unioned; the previously fixed conservative rule can miss a split anchor.

References were sealed before any native predictions were opened, without access to the reserve. Native execution had already begun; no claim that labels predated execution is made. The reference digest is `4e854dd5744a0c94ccc0c938fc6c18968b7f3b5c564e39386e1296e5a05bbbb0`. Every reference source hash, range, decorator boundary and complete lexical qualname was independently checked.

A separate evaluator review found two integrity omissions using synthetic data: coordinates without evidence content could pass validation, and incomplete closure manifests could omit consumed outputs. Both were corrected before any prediction inspection, with the original grader registration preserved and a separate integrity amendment. The relevance policy did not change. The amended evaluator passed 24 focused tests, 14 existing public benchmark tests and 79 independent checks including synthetic probes; the independent review has no remaining blockers. Its receipt is retained. These tests validate the harness and contract, not retrieval accuracy.

## CPU measurement

The host is an Apple M1 Pro with ten logical CPUs and 32 GiB RAM. Each revision runs serially: fresh preparation process, fresh symbols process, fresh files process, then deletion of only that run's owned index. Exact source-context vectors are cached across these revisions; model assets already exist in the offline prepared cache. Source snapshots and closed responses remain. No two native revision index/query processes overlap.

All latency figures are elapsed wall time on the CPU backend. Per-query accumulated process CPU time is retained separately and can exceed wall time because the models use multiple CPU threads. For each route, a fixed unrelated query warms the prepared pipeline; then the first original question is timed through normal `find_best`, compact rendering and JSON serialization. Preparation, warmup, wall time, CPU time and process peak RSS are recorded separately. Preparation is not included in prepared-index search latency. Query RSS includes loaded models and warmup. RSS is per process, not whole-machine memory; the two lightweight orchestration processes are additional. A route is measured once per physical question, yielding eleven latency samples. p95 uses linear interpolation, not 18 duplicated samples.

Previously running RepoQA and Semble jobs remain active on the same host, so these are observed timings under contention. Successful-query timings and all-request timings are both reported to expose fast failures. Every measured route process must attest CPU-only providers, the fixed budget and no PyTorch/Transformers imports.

The compact renderer preserves every returned evidence line with its original physical line number. Scoring validates the structured source-bound identity/evidence used to produce that same compact response; display text is never parsed to invent a reference identity.

## Results

Primary route interpretations are bold below. Every quality denominator includes the query failure.

| Route | Level and target | Top-1 | Top-10 |
|---|---|---:|---:|
| symbols | **LEVEL-2: responsible unit** | 6/11 (54.5%) | 7/11 (63.6%) |
| symbols | LEVEL-2: reference file only | 6/11 (54.5%) | 9/11 (81.8%) |
| symbols | **LEVEL-3: positive context unit** | 3/7 (42.9%) | 5/7 (71.4%) |
| symbols | LEVEL-3: reference file only | 4/7 (57.1%) | 5/7 (71.4%) |
| files | LEVEL-2: responsible unit | 0/11 (0.0%) | 1/11 (9.1%) |
| files | **LEVEL-2: reference file only** | 2/11 (18.2%) | 8/11 (72.7%) |
| files | LEVEL-3: positive context unit | 0/7 (0.0%) | 0/7 (0.0%) |
| files | **LEVEL-3: reference file only** | 3/7 (42.9%) | 5/7 (71.4%) |

LEVEL-2 symbols: six correct first, one correct at rank 2, three completed questions absent from the final ten, one query error. LEVEL-3 symbols: three correct first and two more within ten. See [case analysis](failure-analysis.md) and [machine report](report-v235.json).

## Search latency and RAM

One first original request after fixed warmup per physical question and route. Successful requests are shown here; the machine report also retains all eleven timings, including the faster error.

| Route | Successful queries | p50 | p95 | Maximum | Query process peak RSS |
|---|---:|---:|---:|---:|---:|
| symbols | 10/11 | 6.075 s | 9.363 s | 10.635 s | 1.184 GiB |
| files | 10/11 | 4.876 s | 7.924 s | 8.714 s | 1.187 GiB |

Preparation: 21.61 minutes total across eleven sequential revisions; median 76.02 s, maximum 505.04 s, peak process RSS 1.655 GiB. The first preparation, including a cold source-context build, takes 505.04 s; later preparation can reuse exact source vectors. Fixed warmups are retained separately in each route provenance file.
Largest index measured immediately after preparation: 77.75 MiB. Final reusable source-context cache: 214.95 MiB. Every owned index was deleted after both route outputs closed. Existing shared model assets are not included in these disk figures.

## Per-revision measurements

| Revision | Source files | Preparation | Symbols query | Files query | Symbols / files peak RSS |
|---|---:|---:|---:|---:|---:|
| mwaskom__seaborn-3069 | 310 | 505.04 s | 7.807 s | 5.768 s | 1.140 / 1.170 GiB |
| mwaskom__seaborn-3187 | 323 | 56.63 s | 10.635 s | 8.714 s | 1.184 / 1.187 GiB |
| pallets__flask-5014 | 251 | 224.86 s | 3.222 s | 3.234 s | 1.090 / 1.075 GiB |
| psf__requests-1142 | 113 | 100.75 s | 4.970 s | 4.063 s | 1.056 / 1.059 GiB |
| psf__requests-1724 | 117 | 76.02 s | 1.644 s (error) | 1.671 s (error) | 1.086 / 1.103 GiB |
| psf__requests-1766 | 120 | 18.93 s | 5.434 s | 4.568 s | 1.102 / 1.095 GiB |
| psf__requests-1921 | 121 | 56.99 s | 4.996 s | 3.951 s | 1.077 / 1.053 GiB |
| psf__requests-2317 | 128 | 61.60 s | 6.716 s | 5.184 s | 1.096 / 1.070 GiB |
| psf__requests-2931 | 135 | 81.21 s | 4.139 s | 3.505 s | 1.072 / 1.089 GiB |
| psf__requests-5414 | 97 | 103.30 s | 7.737 s | 5.964 s | 1.104 / 1.110 GiB |
| psf__requests-6028 | 97 | 11.26 s | 7.266 s | 6.960 s | 1.124 / 1.092 GiB |

## Evidence and reproduction

The capture closure pins every response, resource record, coverage record and group preparation log. The grader refuses incomplete/unbound outputs and checks every returned source hash, range and excerpt against the original bytes before scoring. All 200 returned result slots passed those checks. The original text-adapter report hash remains `b46ae4aa7ded74ace5c35e51e98df6f42c0d444bdff8cfa27c4ac24bdbc145c0`.
Scripts are versioned in `experiments/search-engine/`: `register_native_v235.py`, `capture_native_v235.py`, `grade_native_v235.py` and their focused helpers/tests. Registration requires the pinned public source archives and original V224 request/source registration. Capture requires the recorded frozen source tree and preprepared offline CPU model runtime. Use a new output directory for reruns; closed outputs/reports are never replaced. Run grading in ordinary Python, without `-O`, and verify the independent review and grader amendment pins before invocation.
Run registration, exact queries/source hashes, closure, per-route responses/provenance, reference seal/review and grading invocation are retained beside this report. Snapshots, model weights and disposable indexes are kept outside Git. Original license and notice texts for the source excerpts are in `licenses/`; code remains under the corresponding upstream licenses.
The native result is below the project’s 90% top-1 / 98.5% top-10 development targets, and several CPU searches exceed the desired 3–5 seconds. This public pilot diagnoses a generalization gap; the private reserve stays closed and no release is created.

# Actual MCP bounded symbol ranking V214

Both complete exposed development cohorts were captured before opening fixed
Gold. All400 calls use normal default MCP stdio; the source425-file freeze
is b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079.
Every native candidate pool is identical to201, and all240 English complete
orders exactly match closed213 BEFORE grading. Queries, references and English
language labels were not edited. The sealed reserve remains CLOSED.

| Fixed English development |201 top1|214 top1|Recall10, unchanged|
|---|---:|---:|---:|
|Original120|113/120 (94.17%)|110/120 (91.67%)|118/120 (98.33%)|
|New120|95/120 (79.17%)|108/120 (90.00%)|119/120 (99.17%)|

The >=108 requirement is met independently in EACH cohort. All400 bilingual
regression rows are retained: original189/200 top1,197/200 Recall10; new176/200
top1,195/200 Recall10. Spanish is not the acceptance target. These are exposed
development results, not an unseen population-accuracy estimate, not a private
reserve pass, and not a new Semble benchmark score.

## Source and mathematical contract

Nonexact symbol candidates receive (original-card logit + complete-owned-code
logit)/2 from the same published Ettin68M, max1024tokens. The extra executable
view is accepted only whole:<=64lines,<=12000chars,complete pair<=1024tokens.
Otherwise its score is the original-card score. No arbitrary prefix cut.
Stable syntax-relation, requested test-case and explicit code-operator
preferences follow. A requested path retains final priority. Unknown syntax
does not remove candidates. Exact lookups and aggregate class/module/file RRF
stay as201. See the207–213 evidence for isolated controls and failed approaches.

The relations observe direct source syntax only: explicit exception cause,
same-mapping/key previous-value record around assignment, and returned
flag-or-assigned-call. They are not interprocedural or execution proofs. Valid
delegates are retained. No labels, query IDs or repository names enter the
product policy. This small development improvement still needs external
generalization checks;90% on a repeatedly inspected set is not independent proof.

## CPU and memory

All actual ONNX providers were CPUExecutionProvider for reranking and contextual
retrieval,1024tokens, no Torch/Transformers/sentence_transformers imports.
Complete warm MCP English240 latency: p50 2418.77ms,p95 3734.28ms,max4885.30ms.
All400:p50 2582.89ms,p95 4023.92ms,max5185.41ms. Peak WHOLE-server RSS is
2003845120bytes (2.00GB decimal,1.87GiB). All observations and outliers remain.
Index preparation and explicit warmup are separate; full-process CPU totals,
warmup, per-repository file counts and RSS are in costs.json. No GPU is required.

The approximate1s/100files target remains unmet on several small repositories;
the model's fixed overhead is visible. Do not claim that scaling target passed,
that costs are statistically isolated from all machine activity, or that lower
RSS than201 proves a causal memory optimization. This run validates the actual
quality and measured CPU cost of the new ranking policy.

## Verification and reproduction

37 targeted tests use real parsed fixtures and miniature ONNX inference.
Full suite14998passed with10existing xfails; mypy360sourcefiles clean. The earlier
full-suite attempt was interrupted before a snapshot-provenance fix; only the
complete final log is counted. Source/input parity covers all1280symbol inputs
and128nonexact English orders. No existing failures are hidden or suppressed.

manifest.json records original logical paths, source SHA256, deterministic gzip
payload hashes and byte counts. Restore the recorded corpus/source/model pins,
the201 base plus complete SOURCE-WORKTREE.patch (including added modules), then
run the capture driver before the grader. Map external absolute input paths to
their restored byte-identical files. Prior207–213payloads retain all fixed exposed
references and the replay; no sealed input is required or included. No release.

# Native ranking diagnostics — ALL200 development

The diagnostic observes Ken's actual ranking rather than estimating feature
weights. Tracing is opt-in at `EvidenceReranker.rank(..., trace=RankingTrace())`.
Each observation retains the model fingerprint, actual feature matrix, proposal
signals, owner identities, scores and final positions. `trace.compare(a, b)`
returns both candidates' paths through every tree and their exact score margin.
Query text is excluded from ordinary trace export unless explicitly requested.
Tracing adds no dependency or automatic logging and does not change ordinary
responses. This is an engine interface, not a new CLI/MCP parameter.

The clean producer is a Git export of checkpoint `8fcd2d0` plus only the owned
diagnostic changes and already tracked benchmark helpers. It excludes copied
foreign working-tree changes. Its source receipt is
`7e470b3803391476d62691ca522ae73d6f3fd950d6d82b5bfd2d6b925c4b8657`.
All200 native outputs closed before reference analysis; registration SHA256:
`e6e5582602b02dd7c48e437f4d2e090e62d00f70188993873e66e179d176bdb0`.
Every full pool/card/query-expansion digest matches the closed v114 replay.
All eight repository trace files are byte-identical to the earlier v118 capture.

## Observations

- Identity top1:168/200=84%; Recall10:197/200=98.5%; Recall20:198/200=99%.
- All200 acceptable pieces occur in the complete projected candidate set.
- Of32 wrong first results,29 have the correct piece in top10, one at11–20,
  and two below20. None is removed from the denominator.
- All101764 captured owner scores and the complete owner order reproduce exactly
  from the registered models and251 captured feature values.
- By requested kind, wrong top1 counts are class6, module6, symbol7 and file13.
- `rrf_rank` leads positive first-divergent-tree margin accounting in9/32 failures;
  `expanded_documentation_fraction` leads in4. This is a hypothesis for further
  controlled tests, not a causal estimate or a reason to delete either signal.

For example, an Ajv serializer module loses to a JSON-schema types module by
0.507230. Trees first separating on reciprocal retrieval rank account for
+1.670859 of that gap, while call similarity and documentation coverage favor
the correct implementation. Other failures select a test consumer over its
definition or a data schema over the requested implementation. Actual paths,
all values and successful cases are retained, not just selected examples.

The report is `output/development/native-ranking-diagnostics-owned-report-v120/`:
`report.md`, `summary.json`, `all-cases.jsonl`, and `failures.jsonl`.
The complete traces are under `output/development/native-ranking-diagnostics-owned-v120/`.
Tree deltas grouped by their first divergent split account for the forest margin;
they do not claim fixed linear weights, isolated causal effects or SHAP values.

## Verification and limits

267 retrieval tests and36 focused benchmark/model-control tests pass. Mypy passes
all337 clean source files. Mutating the explanation's threshold equality makes
the interaction/margin test fail; the production source and frozen producer are
unchanged by this mutation check.

This instrumentation does not increase accuracy. These are exposed development
queries, not private acceptance. Identity is distinct from sufficient evidence:
the independently closed v116 native result is102/200=51% joint, so the90%
joint acceptance target remains unmet. No new reranker trial or default change
was introduced. Follow-up work must test a ranking hypothesis across all cases,
report gains and losses, preserve Recall10 and verify actual returned evidence.

# Qualified source identity: actual public CPU results

Ken now preserves an explicit `namespace::Qualified.symbol` before semantic
ranking. A unique matching source owner uses the existing exact-source response,
without loading models. The namespace and full member must both match; caller
questions, behavior prose, multiple targets and trailing clauses retain semantic
search. Ordinary name resolution and learned scoring are unchanged. Java matches
the physical package directory, not a package declaration stored in the index.

Frozen source receipt:
`3f56b5848be8fcb44ce6006b754a6cbfb6d609c872521437be5ceeefd6b36197`
(422 files, isolated correction on ef211af). The complete real public MCP captures
both closed before grading with the same pinned exposed references/evaluator.
No query dropped; no private reserve opened. JSON and default compact responses
agree in every repository. Both model sessions use CPUExecutionProvider and no
Torch/transformers import. Prepared-index warm-search timing includes the public
transport and result construction; startup/model preparation is separate.

| Cohort, all 200 queries each | Previous actual default | Corrected actual default |
|---|---:|---:|
| Original balanced development top1 | 191 (95.5%) | 191 (95.5%) |
| Original Recall10 | 197 (98.5%) | 197 (98.5%) |
| New symbol-only development top1 | 150 (75%) | 159 (79.5%) |
| New symbol-only Recall10 | 195 (97.5%) | 195 (97.5%) |

Original: class49/50, module48/50, file48/50, symbol46/50 top1; all200 complete
ordered identities exactly equal frozen145. New200: qualified lookups40/40,
behavior119/160; EN93/120, ES66/80. The nine gains are explicit named lookups.
This fixes identity loss, not semantic discrimination. These two cohorts have
different composition; do not pool them into an independent accuracy claim.

| CPU resource observation | Original200 | New symbol200 |
|---|---:|---:|
| p50(ms) | 2340.075 | 1658.374 |
| p95(ms) | 3646.425 | 2876.603 |
| maximum(ms) | 4788.266 | 3543.414 |
| process peak RSS(bytes) | 2102460416 | 1928626176 |

These are observed separate runs, not randomized paired causal speedup or exact
RAM cost estimates. The original small113–141file repositories still have
1.98–2.32s median, above1s/100files. A roughly2GB whole-process peak remains a
limitation. A single exact lookup avoids model loading, but the multi-query
benchmark process also handles behavior queries. CPU results here do not prove
GPU acceleration or performance on other hardware.

Initial19targeted tests:18fail/1pass before implementation. Final21new tests
cover English/Spanish parsing, full namespace/member binding, Python/TS/Java
paths, cross-module rejection and model-free public best-search. Mutation that
ignores namespace fails; exact source restored. Targeted86passed. Final whole
suite14944passed,10preexisting xfail,525.38s,exit0; mypy357source files clean.
An initial partial suite was interrupted after discovering zsh's readonly
`status` variable in the exit recorder. A second was interrupted before final
source freeze to add the empty-match fast path. Both logs are preserved; only
the final completed run validates the frozen production bytes.

The first model-free400query diagnostic is a projection, not an API benchmark,
and lacked contemporaneous imported-module observations. A separately registered
later replay172b verifies73ken module origins/hashes under freeze172, observes
no model imports and reproduces all400observations byte for byte. This later
replay supplements, but does not retroactively repair, the original provenance.
The actual MCP measurements above are separate complete captures.

Two fixed development-only compositions were rejected. Raw neural order plus
exact identity gives189/197 original and169/195 new; raw neural already resolved
all40locators. Prior query-role order plus exact gives190/197 and172/193, one
gain. That second arm uses a LEGACY pool:32query pools differ from the current
195Recall10 pool, so the difference does not isolate a role effect. No fit,
threshold sweep or runtime policy from these arms was promoted.

Source-pair investigation records all31raw-neural new misses:26correct pieces
are already among ten, five absent. Examples include `expr` (OR) ahead of
`and_expr` (AND), a lock test ahead of the8line lock factory, and documented
`MonkeyPatch.setattr` ahead of `annotated_getattr`, which constructs the required
error and retains its cause. These identify plausible semantic/role confusions;
they do not prove what internal neural representations caused the logits. The
native/neural fusion loses ten net new behavior hits relative to raw neural
(119 versus129 of160), while gaining two original hits overall. A global switch
does not reach the public development gate and is not promoted.

Latest independent balanced acceptance remains177/200 top1 and198/200 Recall10
on frozen145, below90%. Fresh balanced reserve remains closed. Before opening it,
require original>=180top1/197Recall10 and new-symbol>=180top1 with all200queries.
The current new159fails that prospective gate. No release/tag/version bump.

Full public metrics/strata: [summary.json](summary.json). The compressed evidence
archive and independent reference/scorer review are recorded in
[checkpoint.json](checkpoint.json). It preserves source patches, producer bytes,
closures, all400actual responses/resources, projection controls and initial
failures. Private acceptance reference payloads are excluded.

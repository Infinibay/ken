# Best search configuration by default

The user explicitly requested on16October that normal CLI and MCP calls select
**the best complete measured configuration**, not just a better embedding.
This authorizes default integration, while release/tags remain forbidden.
It supersedes earlier no-default-promotion instructions for implementation;
it does not waive quality, compatibility, source fidelity or CPU/RAM checks.

## Evidence and limits

- Among seven static encoders compared in development400, Potion Code16Mv2
  led: role identity167/400 and strict156/400. These historical fragment metrics
  are not the present piece-identity metric and do not imply90% alone.
- Current full experimental profile uses Potion Code16Mv2, CodeRankEmbed137M
  INT8 contextual source views, ES→EN local CT2INT8 expansion, native251-feature
  forest, requested-piece262-feature forest, Ettin68M FP32 top10 and RRF60/.5.
- CPU134 uses neural batch1,4intra-op threads, pair cap512; context/translation
  stay2threads. On original200:180top1,197top10; complete returned orders equal132,
  p502.518s,p953.863s,peak2.001GB. CPU baseline132 is4.162s/5.334s/1.976GB.
- The shipped/public default is still the older static-Qwen profile. Several
  experimental dependencies are injected by PreparedKen from workspace paths.
  Changing only recommended_model or an API default does not install the winner.
- Source and engine controls are sealed. New independent200 is curated and
  cross-reviewed, with no implementer access to Gold or query content. Runtime
  controls132/134 are frozen; do not inspect their new quality outputs to tune
  production integration. Freeze any production arm before Gold grading.

## Concepts and boundaries

**ModelAssets** resolves a versioned manifest to a local cache, verifies hashes,
and downloads only declared public artifacts. No absolute experiment paths,
remote model code, runtime Torch dependency, or hidden precision changes.

**SearchPreparation** builds passage/static vectors, complete owner context and
source-view matrices for one project generation. It owns incremental invalidation
and uses mmap storage. Model setup/indexing is explicit progress, separate from
prepared query latency; no silent legacy fallback pretending to be the best.

**BestSearchRuntime** loads those resources, retrieves native owners, constructs
requested class/module/symbol/file pieces, applies the piece forest, reranks the
same top10 with the fixed neural/fusion policy, validates source, returns pieces.
It consumes SearchRequest and returns normal SearchResponse data. Token inputs
for the neural model preserve the measured compact policy independently of UI
presentation. It must not import ken.bench or experiment modules.

**ProductionRankModels** packages generic source-only models with training and
feature receipts. Repository-excluded validation folds remain validation tools;
never pick an evaluated repo's heldout model by repository name in production.
Use a prospectively declared pooled fit or aggregation, with no new200 labels.
Validate the actual resulting public runtime; do not transfer90% from folds.

**PublicSearch** is the one orchestration path used by CLI and MCP, with
requested-piece inference/override, compact text by default and native JSON
opt-in. Explicit legacy remains available. Existing stored vector model IDs must
not be mixed with new query vectors; migrate through generation-aware reindexing.

**ExecutionResources** preserves CPU availability and bounded RAM, with the
measured CPU policy. Optional usable accelerators require source-free parity and
cost checks before selecting a faster provider, and CPU fallback if unusable.
No GPU is required for setup, indexing or queries.

## Execution slices

1. Finish/verify/commit compact public presentation and real examples separately.
2. Introduce a portable pinned Model2Vec backend, tested against the actual Potion
   control; make the measured static encoder the new-project default while
   preserving existing project pins/explicit user overrides and migration.
3. Extract portable CPU contextual/neural loaders and prepare/cache source views
   through production indexing, with small real-ONNX tests and source receipts.
4. Fit/register production numeric models using original development only.
   Integrate requested-piece assembly and fixed neural policy in BestSearchRuntime.
5. Connect default CLI/MCP routes, index/setup status and explicit compatibility.
   Test all scopes, empty/stale inputs, read budgets and persistent MCP reuse.
6. Freeze and exercise complete public CPU runtime on original200 and additional
   independent200, preserving all denominators, unit identity and native top10.
   Gold scoring stays with curators and occurs only after all arms close. Report
   cohorts separately and actual measured defaults, not a synthetic runner claim.
7. Review, document examples/measurements, commit and push main without release.

Additional200 uses the same8repos, not new-repository generalization; source files
are disjoint from175opaque principal/calibration exclusions. v104 remains unopened
and its overlap is not verified. A90% observed sample is not a95% confidence
population lower bound of90%. No acceptance thresholds are reduced.

## Integration checkpoint: a047e09

Compact CLI/MCP presentation and public examples are published. The portable
Potion backend is published and its single-change replay136 returned identical
cards/units/pool hashes and orders on all200original queries:180top1/197top10.
Global model/profile recommendations remain unchanged until the complete public
runtime is ready. Private references for the new200 remain closed.

ContextEncoder and exact portable CT2 preparation are implemented with real
small-model/filesystem tests, not yet activated in public search. Frozen137 and
138 represent these changes separately, with complete original200 replays queued
after frozen132/134finish their public-only new200 captures. No new quality
feedback is available to choose production policy.

The same measured CT2 model.bin and source/target SPM files are publicly hosted
at Prukario/opus-mt-es-en-ct2-int8@ad91ad1697ea1761111ff4c179400796d085b347.
Configuration and vocabulary have identical JSON values; indent2/ensure_ascii
normalization reproduces the exact measured files. This avoids runtime Torch,
conversion of neural weights, or publishing new model weights. Source:
https://huggingface.co/Prukario/opus-mt-es-en-ct2-int8/blob/ad91ad1697ea1761111ff4c179400796d085b347/model.bin.

## Prospective production numeric-model portfolio

Validation-only repository-excluded folds cannot be selected by a repository's
name in normal search. Two generic candidates may be evaluated and chosen on
original exposed development only, before any new200Gold scoring:

1. Refit the original fixed training recipe on its complete original development
   inputs, with the existing feature schema/hyperparameters and no new labels.
2. Form a fixed equal-weight mean of all registered validated numeric forests. Use16native folds and8piece folds, as recorded in the source registries. Scale
   each leaf by the reciprocal of its role's model count and concatenate trees; runtime remains the existing additive
   NumPy forest. Native and piece models are aggregated independently. There is
   no per-repository model choice, learned weighting, private-case lookup or HPO.

Record exact source-model/training hashes, feature schemas and chosen model
fingerprints. Scores on original200 are development evidence, including any
training reuse; independent new200 is reported separately after the final public
arm is frozen and closed. Do not transfer the existing90%fold result to either
unmeasured generic candidate. Further development after independent feedback
requires preserving that cohort's status as exposed feedback and a new untouched
acceptance cohort; never quietly reuse it as fresh acceptance.

Portfolio clarification before generation/any new Gold: the native69registry has
16folds, while piece126has8. Use all16native folds and all8piece folds, rather
than limiting the native model to the8evaluation repos. This is a metadata-driven
correction to the initial fold-count assumption, not quality-feedback selection.

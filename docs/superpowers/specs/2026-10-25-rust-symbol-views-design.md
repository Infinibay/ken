# Bounded symbol relevance views in native retrieval

Continue the approved migration inline, Linux x86_64 only, preserving originals
and local evidence. The next PieceSearch/SymbolRanker needs two relevance views
before applying explicit source-operation preferences. This slice implements that
complete neural policy, not the later source witnesses or full search frontend.

Caller: score existing cards through a PairedReranker, then
rank_symbol_views(query,&descriptions,&card_scores,&reranker). OwnerDescription
already owns exclusive source projection. Symbol relevance owns whole-code
admission, one fresh deduplicated inference, fallback, equal means and stable
order. The native ONNX adapter owns text conversion and model delegation only.

PairedReranker exposes pair_fits(query,document)->Result<bool> and
score(query,documents)->Result<NeuralScores{scores:Vec<f64>,details:Value}>.
OnnxPairedReranker wraps Arc<OnnxReranker>; F32 logits are promoted exactly, not
normalized. An empty score request delegates the model's empty path without
validating/converting query or loading resources. Other model calls require
scalar Unicode, matching existing native model adapters. No new dependency.

complete_code_view(OwnerDescription)->Result<Option<PythonText>> uses the frozen
Python projection: `symbol {path} {qualname}` + newline + signature + newline +
`Implementation:` + newline + executable. Absent qualname prints `None`, empty
qualname stays empty. Require the whole executable to have at most64 Python
splitlines and the full projection at most12000 Python codepoints. Never take a
prefix. Reuse unicode::splitlines for boundary semantics; isolated surrogate
points are non-boundaries and remain lossless in returned text.

rank_symbol_views requires matching description/score counts and native top10.
For each admitted whole view call pair_fits in original order; oversized views
never call it. Preserve first-occurrence order when deduplicating accepted text.
Call score once even if the fresh set is empty. Expand fresh logits back to every
candidate; rejected views reuse their own original score. Compute exactly
(original+code)/2, including IEEE overflow, and stable descending means. Return
order,code_scores,mean_scores,code_view_used,additional_inference. Preserve input
descriptions/order/membership and metadata. Registered-model scores must be finite
and one per requested document; reject broken collaborators before indexing.

Approaches: putting this policy inside the ONNX adapter mixes model mechanics
with retrieval decisions; porting all source-operation parsers now expands into
another responsibility. A focused symbol_views policy plus a paired-model
interface composes naturally with the later SymbolRanker and PieceSearch.

Before Rust implementation, capture new observations from frozen SymbolRanker
with neutral requests (no source/test/operator preferences), supplied cached owner
descriptions and an observed deterministic model collaborator. Also capture new
full first-card/second-code frames using the real production Ettin source and
independent original preparation. No old20/23/2616corpus/suite recapture. Include
the previously deferred fusion grouping witness [0,1],weight.5,offset2^53 as a
separate new observation; preserve the2616fixture unchanged.

Validation: original code/owners/inputs/records authenticated, one first capture;
Rust caller tests RED→GREEN, exact projections/calls/flags/fake-F64/order/errors,
char/line/Unicode/empty/duplicate boundaries and real ONNX adapter/preparation.
Real-model numerical bounds stay1e-5+1e-5abs; policies/order/token details exact,
phase timings bounded separately. Run affected complete native suites,fmt/strict
Clippy, x86 model/syntax CI, input-only native execution and archived replay.
One fresh final whole-plan review, one Important repair pass, no re-review.
Only symbol neural-view capability can close; full symbols/PieceSearch/M4/global
and other x86 model profiles remain pending. Preserve all local raw, no install.

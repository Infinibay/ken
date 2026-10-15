# Small trained late-interaction control on faithful source7 v70

61's same-encoder projected token interaction scored284/400 prepared, while
69's real source7 contract/body control scored285/400 prepared. Neither reaches
90%. Test a genuinely trained small token head rather than attributing published
ColBERT results to CodeRank tokens not trained for MaxSim.

Official model: answerdotai/answerai-colbert-small-v1, Apache2,
revision934fa8bb4ce2284f4c2baa232d81aca4d076fa5e. Only official int8 ONNX33948650B,
tokenizer/config/card were downloaded in68 with byte hashes; no remote Python,
GPU, external inference or uploaded code/queries. Graphde45baeaa7a48cda647fcf71582e2a0920dca303654034570aa6144d84526283.
Primary provenance: https://huggingface.co/answerdotai/answerai-colbert-small-v1
and https://www.answer.ai/posts/2024-08-13-small-but-mighty-colbert.html;
marker/mask mechanics from original Stanford ColBERT query/doc tokenization and
model code. Published BEIR performance is not a code-search/strict90% result.

One CPUExecutionProvider session,2intra/1inter threads,batch1. The graph returns
already-normalized96dim token vectors; validate them, do not silently normalize
again. Insert actual registered Q=1/D=2 afterCLS, preserving every retained input
token and offset; do not replace the first source word with the marker. Doc
max300 follows official config; query max128 is a declared extension from32 so
longer original requests retain more constraints, fixed before quality fits.
No padding or MASK augmentation, matching official ONNX do_query_expansion=false;
keep query punctuation and doc punctuation skiplist IDs as registered. CLS/D/SEP
remain document tokens; source offsets refer to projection text, not file bytes.

Read every source7 contract/implementation text from69's completely registered
source DBs, no relevance labels/query-dependent source selection. Verify all16
source preparation receipts, model policy and source files/generations. Encode
every distinct projected text with this33.4M model before any query access.
Do not reuse CodeRank token vectors or falsely relabel another encoder space.
Compact validated unit96dim source rows by round127/int8; record approximation
error and all unit/owner/view mappings, token IDs/offsets and file hashes. Stream
source units from SQLite and token rows to disk; use read-only mmap for queries.
DF counts canonical owners with a token in either view once, not repeated words
or two view votes. Record index/preparation time and peak RSS separately.

After all16 sources, derive ALL400 original requests on the fixed fresh66c pools
and69 parent251 features. Encode each distinct original/actual expanded query
once; record all800 ID/view/text/token/vector bindings or an explicit unique-exact
numeric bypass. Same original exact authority and neutral32 only for singleton
bypasses; no scores are fabricated for ordinary candidates. Six MaxSim token
summaries(mean/min/p25/DFweighted/above.5/.7) plus mean-to-poolmax and reciprocal
rank for each query/original-expanded × source/contract-implementation=32features.
These are relevance signals, not proofs of logical conjunction/absence/calls.

Register exactly two fixed controls:235baseline+32=267 trained-token columns,
and251parent+32=283 combined columns. Both keep the current137M contextual
proposal family; this is a complement control, not a claim of replacing/removing
that encoder. Any replacement needs fresh independent proposal/recall/API work.
Use the original160tree settings,16whole-repo-excluded folds and original
eligible_owner labels; native/export scores must be exact. Score all400 with
unchanged ALL-anchor strict references,40-line/12k budgets, failures/missing=0
and every original stratum. Keep source/query/fit/render artifacts, no private
acceptance or public labels used for fitting. No promotion without actual API
and final uncontended CPU/low-RAM certification. Negative results are retained.

70b adds a pre-fit attestation using replay_parent (9 regression tests) for all
400 request IDs,167360 positions,51 original input artifacts and the complete
251-column parent prefix in each283-column child. It also verifies all800
actual original/expanded text bindings. The70 producer/freeze/ranking are kept
unchanged: its current inputs independently matched, but its generic same-count/
same-file-hash checks did not reject a future reordered parent cache.70b fits the
same two fixed controls after these explicit checks; no source re-encoding,
formula, criterion or query alteration is needed or permitted.

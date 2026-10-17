# Semble public1251 × three contextual encoders — V323

Register before new outputs; all3753 outputs close before grading. OriginalV219
requests SHA c8ccb7efc678ccb97b5a03442047ee630b1e225d6009682584d0ffc6f14aca53,
all1251queries/all63repositories, unchanged source commits/annotations/scorer.
The public benchmark has already been exposed. Private V104 remains CLOSED.
No release. No ranking/model fitting or query/target editing during this run.

Freeze accepted current Ken plus the UTF8 binary-admission/migration fix. Each
arm uses public find_best(scope=files,piece_kind=auto,purpose=auto,limit10,
max_chars12000), compact rendering + canonical JSON serialization in timing.
Keep every native rank slot. Score exact original Semble target_rank/ndcg_at_k;
report Hit@1/10, micro-query AND macro-repository NDCG@10. These largely file-only
annotations do not establish strict correct-function accuracy. Historical
Semble0.7.0V219 quality may be shown as a clearly dated reference; historical
latency is not a matched speedup measurement.

Only contextual encoder changes: CodeRank137M INT8 CLS control; Jina code161M
INT8 official graph + masked mean; Muninn-small47M CLS official BF16 checkpoint
exported to CPU FP32, native prompts, 384native dimensions zero-padded to768.
Same512token limit/batch1/CPUExecutionProvider/2intra1inter. Use native model
prefixes/pooling verifiedV320/V322; preserve their exact model/text cache keys.
PotionCode16Mv2static, native/piece forests, query expansion and Ettin68M1024
unchanged. Never switch to the old wrong Muninn mean policy or silent fallback.

Pin all original index-admitted source bytes (12074files); copy them and existing
SQLite/vector stores into owned scratch. Existing original repos/caches stay
read-only. Rebuild source passages with current extractor, then use the exact
same rebuilt index and copied source for all arms. Indexed binaries may remain
in ci_files, but malformedUTF8/NUL source creates no retrieval passages.

Serial per-repository/arm subprocesses; arm order rotates by repository so each
arm occupies each position21times. No competing benchmark/model/test jobs
while query timing. One generic unscored warm query, then each original query
once. Timing is full ready-index API+render+JSON wall and processCPU time. CPU
p50,p95,max and process peakRSS reported separately from setup/index/warmup.
RSS is a high-water mark including model load/source preparation, not an
incremental model-only memory measure. Source-only cache prefill uses4concurrent
batch1 calls, with bitwise serial/parallel parity on5actualsourceviews. Prefill
joins completely before query timing. Reused vectors require identical model
key, source text and hash; never query labels. Report cache reuse and elapsed
preparation; this is warm source-cache setup, not a cold full-index cost.

All failures retained in1251denominator/arm, with logs; no filtering supported
languages. Preflight all189workers, originalIDs, source hashes, actual profile
fingerprints/providers, output hashes BEFORE loading any annotations. Close
outputs before scoring. No quality peek/model selection until capture closure.

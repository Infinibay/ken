Independent review of API81 file diagnostics — verified

Both calculations reproduce exactly for all 400 original development queries, with unique IDs, 16 repositories and 25 queries per repository. All recorded input hashes match the current files. API81 responses retain SHA256 `58c24a5525ad8d8ab3dc9281b494f2de403eb6278ee49648d6926c6acf553c99`; Semble normalized responses retain `ea3a6f2a27042f2ab4ec9255d10b57f8fe39e99f6764a6cc9f2ac07a883fc7a7`. A fresh run of the existing scorer produces the exact complete diagnostic JSON; a separate first-index formula independently reproduces all 800 per-query results.

| Auxiliary result | Ken API81 | Semble on these 400 |
|---|---:|---:|
| File top1 | 345/400 (86.25%) | 204/400 (51%) |
| File NDCG@10 | 0.9343641364861627 | 0.6887064071598579 |
| File hit@10 | 399/400 | 343/400 |

The formula credits each relevant file once, at its first original result position, with gain `1/log2(rank+1)`. Duplicate file results occupy positions without further gain. All 400 original alternatives refer to one distinct relevant file per query, so ideal DCG is 1 here. This is not NDCG over a file list deduplicated before assigning ranks. There are 1,706 duplicate file slots in Ken's first ten result positions and 402 in Semble's.

Semble normalization preserves every top1 and result prefix. It removes only tail results for attrs-11 (10→9), boltons-06 (10→8) and junit5-08 (10→7). Independent calculation from the original native paths gives exactly the same per-query file NDCG, top1 and hit@10 as the normalized responses for all 400 queries.

These auxiliary scores assess the returned path alone. They do not establish the exact entity, valid source evidence or visibility of all decisive anchors. The canonical strict API81 result remains 286/400 (71.5%), and its report is unchanged. These development diagnostics also do not replace the separate public 1,251-query, 63-repository comparison (Ken 0.8365028636773735 versus Semble 0.854385). No reference adjudication, fit, tuning, source/data edit or private-reserve access was performed.

Full hashes, formula, all per-query results and normalization witnesses are in [the mechanical report](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/file-ranking-v81-diagnostic-review.json).

## Complete Ken API

| Model | Language | Top-1 | Top-10 | NDCG@10 |
| --- | --- | ---: | ---: | ---: |
| CodeRank INT8 (control) | cpp | 69/100 (69.0%) | 88/100 (88.0%) | 0.7914 |
| CodeRank INT8 (control) | rust | 59/100 (59.0%) | 90/100 (90.0%) | 0.7676 |
| CodeRank INT8 (control) | all | 128/200 (64.0%) | 178/200 (89.0%) | 0.7795 |
| Jina v2 code INT8 | cpp | 63/100 (63.0%) | 83/100 (83.0%) | 0.7413 |
| Jina v2 code INT8 | rust | 58/100 (58.0%) | 87/100 (87.0%) | 0.7442 |
| Jina v2 code INT8 | all | 121/200 (60.5%) | 170/200 (85.0%) | 0.7428 |
| Muninn-small FP32 | cpp | 60/100 (60.0%) | 73/100 (73.0%) | 0.6787 |
| Muninn-small FP32 | rust | 58/100 (58.0%) | 85/100 (85.0%) | 0.7341 |
| Muninn-small FP32 | all | 118/200 (59.0%) | 158/200 (79.0%) | 0.7064 |

## Raw full-owner contextual retrieval

| Model | Language | Top-1 | Top-10 | NDCG@10 |
| --- | --- | ---: | ---: | ---: |
| CodeRank INT8 (control) | cpp | 66/100 (66.0%) | 89/100 (89.0%) | 0.7751 |
| CodeRank INT8 (control) | rust | 67/100 (67.0%) | 93/100 (93.0%) | 0.8109 |
| CodeRank INT8 (control) | all | 133/200 (66.5%) | 182/200 (91.0%) | 0.7930 |
| Jina v2 code INT8 | cpp | 54/100 (54.0%) | 83/100 (83.0%) | 0.6848 |
| Jina v2 code INT8 | rust | 62/100 (62.0%) | 96/100 (96.0%) | 0.7930 |
| Jina v2 code INT8 | all | 116/200 (58.0%) | 179/200 (89.5%) | 0.7389 |
| Muninn-small FP32 | cpp | 46/100 (46.0%) | 77/100 (77.0%) | 0.6064 |
| Muninn-small FP32 | rust | 49/100 (49.0%) | 88/100 (88.0%) | 0.6953 |
| Muninn-small FP32 | all | 95/200 (47.5%) | 165/200 (82.5%) | 0.6508 |

## Local CPU cost

| Model | API p50 | API p95 | Process CPU p95 | Peak RSS including prep |
| --- | ---: | ---: | ---: | ---: |
| CodeRank INT8 (control) | 3.164 s | 4.610 s | 16.032 s | 1.327 GiB |
| Jina v2 code INT8 | 3.092 s | 4.695 s | 16.273 s | 1.664 GiB |
| Muninn-small FP32 | 3.119 s | 4.598 s | 15.565 s | 1.536 GiB |

## Complete original reference spans

Counts include each native document prefix. Reference spans exclude documentation outside their boundaries and additional Ken headers. Selected-view counts are separate.

| Model | Language | >512 | >1024 | >2048 | >8192 | Maximum | Expanded queries >512 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CodeRank INT8 (control) | cpp | 2 | 0 | 0 | 0 | 724 | 0 |
| CodeRank INT8 (control) | rust | 4 | 0 | 0 | 0 | 821 | 0 |
| Jina v2 code INT8 | cpp | 1 | 0 | 0 | 0 | 613 | 0 |
| Jina v2 code INT8 | rust | 3 | 0 | 0 | 0 | 669 | 0 |
| Muninn-small FP32 | cpp | 2 | 0 | 0 | 0 | 691 | 0 |
| Muninn-small FP32 | rust | 4 | 0 | 0 | 0 | 779 | 0 |

## Exploratory raw fusion; not normal API results

| Models | Language | Top-1 | Top-10 |
| --- | --- | ---: | ---: |
| baseline+jina | cpp | 61/100 | 89/100 |
| baseline+jina | rust | 64/100 | 97/100 |
| baseline+jina | all | 125/200 | 186/200 |
| baseline+jina+muninn | cpp | 54/100 | 85/100 |
| baseline+jina+muninn | rust | 60/100 | 91/100 |
| baseline+jina+muninn | all | 114/200 | 176/200 |
| baseline+muninn | cpp | 52/100 | 82/100 |
| baseline+muninn | rust | 57/100 | 92/100 |
| baseline+muninn | all | 109/200 | 174/200 |

## Paired repository bootstrap

10,000 paired resamples, stratified as ten C++ and ten Rust repositories per replicate. These are descriptive development-set intervals.

| Candidate vs control | Metric | Net percentage points | 95% interval |
| --- | --- | ---: | ---: |
| Jina v2 code INT8 | top1 | -3.5 | [-6.0, -1.5] |
| Jina v2 code INT8 | top10 | -4.0 | [-8.5, +0.0] |
| Muninn-small FP32 | top1 | -5.0 | [-9.5, -1.0] |
| Muninn-small FP32 | top10 | -10.0 | [-14.5, -6.0] |

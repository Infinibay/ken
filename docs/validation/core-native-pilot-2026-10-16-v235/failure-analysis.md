# Observed native failures

The engine and references remained frozen. These observations use the closed normal responses; this run did not add stage-by-stage ranking instrumentation. An item absent from the final ten might have been lost during retrieval, owner selection, piece selection or later truncation. Its exact elimination stage is not established here.

## LEVEL-2, symbols route

Six of eleven questions return the responsible callable first. The remaining five are:

| Revision | First result | Responsible target | Final target rank | Observation |
|---|---|---|---|---|
| seaborn-3069 | `scales.py::Nominal._setup` | `plot.py::Plotter._finalize_figure` | Outside 10 | The top result concerns the named scale. The responsible owner applies final axis limits. Another function in `plot.py` appears at rank 6; matching that file is insufficient. |
| requests-1724 | Query error | `sessions.py::Session.request` | No response | The unchanged 7,476-character report exceeds the frozen reranking query budget. It remains a miss in both original levels and routes. |
| requests-1921 | `utils.py::default_headers` | `sessions.py::merge_setting` | Outside 10 | The returned top function supplies headers; the target merges settings and removes keys with `None`. Another member of the correct file appears at rank 3. |
| requests-2931 | `utils.py::to_native_string` | `models.py::RequestEncodingMixin._encode_params` | 2 | The report names a callee; the target caller unconditionally converts a binary payload with that callee. This is the one completed LEVEL-2 failure recoverable solely by reordering the existing ten. |
| requests-6028 | `tests/test_requests.py::TestRequests.test_proxy_auth` | `utils.py::prepend_scheme_if_needed` | Outside 10 | Tests and auth-related methods dominate the ten. The responsible URL reconstruction helper and its file are absent. |

Thus the final candidate list contains the responsible piece for only 7/11 questions. A reranker restricted to these exact ten slots has a 7/11 ceiling on this sample. Three completed questions need a different candidate set, one needs ordering, and one needs successful long-query handling. This does not identify which internal score or candidate stage caused each miss; that requires a separate frozen diagnostic capture.

## Files route

Correct responsible file: 2/11 first and 8/11 within ten. Five of the ten completed first results are documentation, notebooks or history files (`objects_interface.ipynb`, `quickstart.rst`, and three `HISTORY` results). This is an observed destination bias on these reports, not proof of a specific scoring formula defect.

The secondary file-to-piece test gets 0/11 first and 1/11 within ten. Its criterion is deliberately conservative: a file result has no callable identity shortcut and must show the complete presealed anchor in one excerpt. Partial relevant snippets can therefore fail this secondary metric. File hit rates remain the primary interpretation of the files route; these numbers must not be presented as zero useful code or zero correct files.

The symbols route finds the right responsible file more often than the files route (6/11 first, 9/11 within ten), while still missing the correct callable in some of those files. This makes file aggregation and evidence selection concrete areas to investigate later. No engine changes or score adjustments were made in this pilot.

## Limits of the comparison

The previous opaque-text adapter scored 3/18 Hit@1 and 9/18 Hit@10 against original CORE chunk IDs. The native symbols route scores 9/18 and 12/18 only when the two levels are combined descriptively. These are different source corpora and relevance units. The engine is identical, so this is evidence that native source representation changes behavior; it is not a clean percentage-point gain on an unchanged benchmark, an official CORE NDCG result, or a reason to relax LEVEL-2 criteria.

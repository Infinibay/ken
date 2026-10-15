# Actual contextual API on Semble's original public benchmark v48

Repeat all1251 original requests across all63 pinned repositories and original
benchmark_root scopes, with Semble's unchanged official target_rank/ndcg_at_k
scorer and macro-repository aggregation. Keep missing/errors=zero, all primary
and secondary references, atmost10native result slots and current12000canonical
JSON/40visibleline budgets. Native file API is the primary comparable output.
No source labels, category or language hints enter requests or source preparation.

Evaluate the completed v42/v46 contextual235 engine (strict277/400), using the
single numeric model fitted on all16 development repositories. Those16 repos are
disjoint from these63. No fitting, threshold selection or model selection on the
public Semble references. Source v46 differs from v42 only by the token cache
whose exact output parity is independently checked. The later Rust docs repair
is a separate experiment and is not silently mixed into this comparison.

Prepare CodeRank source vectors for EVERY canonical owner of the original
Semble-public Ken source indices, all63 repos, before accessing query texts or
references. Reuse the same pinned CPU graph/tokenizer, full-owned source
projection, prefix512tokens, batch1 and explicitL2 as the strict corpus. Store
every owner/source hash/generation and complete projection, never source
subselected from a query pool. Verify declared sourcefile hashes and pinned
checkout cleanliness. Record source preparation time/RSS separately from search.

Run each repository through a fresh actual API worker with the registered
Potion+local translation+CodeRank encoders, contextual300/static300 broad1200,
fixed235numeric model and retrieved-evidence policy2. Every query is encoded
live; no public query vectors or answer caches. Public worker accepts the
original nonempty perrepo count rather than assuming25 development requests.
Canonical JSON serialization belongs in measured request time. Preserve all
individual responses and worker errors; final report retains all1251 even after
a worker failure. Capture model/source/runtime fingerprints and input hashes.

Compare to the already reproduced original Semble0.8543853795900258 macroNDCG,
935/1251top1, and Ken v21 .8189553482151245 macroNDCG. Public file/any-overlap
top1 is not the strict all-anchor top1 acceptance criterion. No claim of beating
Semble or90% without the corresponding complete measured result. The private
acceptance reserve remains unopened. Concurrent timings are descriptive and do
not establish the final isolated CPU/RAM gate.

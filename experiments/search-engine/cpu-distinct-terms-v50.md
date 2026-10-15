# Distinct source vocabulary without duplicate-token materialization v50

Continue v46's exact-output CPU optimization. The strict277/400 completed API,
all400 original requests, sixteen excluded-repository235 models, model assets,
source indices, contextual scores and source/output budgets remain fixed.
Rust documentation recovery v47 remains a separate source/data experiment.

Vocabulary alignment needs only the first distinct lexical terms, while source
index term frequencies require every occurrence. Keep code_tokens for frequency
semantics. Add code_terms as exactly list(dict.fromkeys(code_tokens(text))) with
an optional nonnegative prefix limit. Scan normalized lexical words in source
order, decompose each distinct raw word once, append each distinct term once and
stop at the existing128query/4096field limits. Retain the same authoritative
word-decomposition/cache/stop-word rules. Do not apply these limits to frequency
indexing or alter tokenization/schema versions.

Use code_terms only in source-feature vocabulary construction and query-term
coverage. Feature names, formulas, pooling, word weights, source inputs and
numeric models remain unchanged. Unit invariants include component/Unicode
overlap, repeated words, every boundary limit and invalid negative limits.

Isolate runtime semantics by freezing v46 plus only tokenization.py and
evidence_features.py changes and this protocol; keep original extractor5 source
policy for the original indices. Declare these source overlays in the new
manifest and verify the entire copied inventory. This is an explicit paired
control, not a claim the later extractor6 source has been indexed.

Rerun ALL400 real API+canonicalJSON responses. Require exact complete-response
equality, original strict277/400 and unchanged request/source/model receipts,
not merely unchanged winners. Retain all errors/missing cases and all timings/
peakRSS perrepo, startup/index preparation separately. The concurrent run is not
a final uncontended CPU certificate. No private acceptance use or threshold change.

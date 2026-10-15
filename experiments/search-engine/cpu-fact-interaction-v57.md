# Source fact and query clause interaction v57

The relation-word union v51 scored270/400, so adding its aggregate coverage is
not justified. Test the different missing mathematical information: whether
separate clauses of the request each match an individual source fact, rather
than matching individual words anywhere in the combined owner text.

Use ONLY v51's independently source-reviewed448100 syntactic relation records,
50967 owners/6139 source hashes and original regions. These are conditions,
guarded operations, value relations, assertion-like spellings and call-expression
syntax, NOT call targets/feasible execution/absence proofs. The rejected54/54b
call-resolution graphs have no role. Preserve v51's explicit unsupported/parser
limits and noRuby corpus; do not silently change source projection semantics.

Before requests/relevance are read, encode ALL relation texts in ALL16 complete
source indices with the existing registered Potion16M native mean+L2 CPU encoder,
original512token pertext policy, no padding/hidden truncation. Deduplicate only
identical text hashes, retaining each owner's kind/span/source provenance. Persist
float32 vectors to memory-mapped arrays with source-only receipts. No larger/new
encoder/GPU/inference service. Query scoring gathers only that pool's fact rows.

Split expanded requests at unquoted and/while/when/before/after/but/without and
comma/semicolon; preserve relation marker text for when/while/before/after/without.
Explicit instead-of/rather-than alternatives form a separate avoid group until
but or punctuation resets it. Keep every nonempty clause; no gold-based splitting
or query filtering. Quotes protect literal keywords. These are transparent text
projections/contrast signals, not a grammar/temporal/negation/absence proof.

Per each five source kinds plus their union, compute original-full and expanded-
full maximum source-fact cosine; minimum and mean across required clauses of each
clause's best matching fact; and maximum alternative-clause/source-fact cosine.
Empty kind/group yields0. Append source log fact count and query-alternative
indicator:32 new columns +235 unchanged baseline =267. Alternative match is a
separate signal, never an asserted contradiction or hand-coded score penalty.

One fixed267-column LambdaMART control, unchanged160tree settings, original
whole-owner labels, sixteen whole-repository-excluded folds and exact native/
export parity. Original v36 pool and v38 base235 rows must match exactly. Render
ALL400 through v50 source5 retrieved renderer with original40lines/10results/
12000canonicalJSON and64-character model metadata. Original strict ALL-anchor
scorer/strata/missing=zero; no per-repo tuning. No prepared/API/private/default,
90% or final resource claim. Independent source-fidelity review precedes promotion.

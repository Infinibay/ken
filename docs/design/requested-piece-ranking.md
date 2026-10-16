# Rank the requested piece

Continuation of the approved search-engine improvement, with the user's current
primary target: >=90% correct requested piece at top1 on all200 development
queries, preserving the native top10 identities and reporting CPU/RSS. Evidence
sufficiency remains a separate measurement. Private acceptance stays closed.

Responsibilities:

- SearchRequest carries an optional explicit piece_kind (class/module/symbol/file)
  independently of the existing coarse target and exact-identity lookup contract.
- requested_piece_kind resolves that explicit value, then file scope or a leading
  requested noun. It never grants exact-name authority or changes the251-feature
  owner model's old query_kind_class meaning.
- A piece candidate identifies one canonical requested unit, its own declaration
  and its supporting members. A member match is evidence about a piece, rather
  than automatically its final score.
- Piece ranking scores only the fixed native top10 piece candidates. The lower
  list remains unchanged, preserving measured Recall10 and avoiding a new retrieval
  confound. The same interface supports directly scored declarations, complete
  piece descriptions and bounded member summaries.
- Frozen experiments own input/source receipts, all200 closure before scoring,
  per-kind outcomes, paired gains/losses and complete pipeline resource reporting.

Representative use:
SearchRequest(query, piece_kind='class') reaches owner retrieval and the optional
piece-ranking stage as a class request. A class composed of many related methods
must compete as that class, not silently borrow the meaning of whichever method
happened to have the highest owner score. Existing callers without piece_kind
and existing profile/model fingerprints remain compatible.

Slices, tested separately:

1. Transmit requested piece kind through the request, benchmark caller and trace.
   Prove identical candidate/card/order scores for all200; expose the type without
   pretending that plumbing alone improves accuracy.
2. Evaluate typed unit scoring against that unchanged baseline, keeping top10
   membership. Start from source-only declarations/fields and member evidence,
   avoid benchmark paths, references or hand-written per-query exceptions.
3. Retain only demonstrated improvements; test subsequent changes independently.
   If a numeric piece model is fitted, exclude the entire evaluated repository
   from its training and record that development CV is not private acceptance.
4. Run full source, compatibility and CPU/RSS checks on the final frozen candidate.

No release or production default promotion occurs merely because development
cross-validation reaches its target. No hidden Gold, query rewriting toward known
answers, smaller denominator, larger card budget or test suppression is allowed.

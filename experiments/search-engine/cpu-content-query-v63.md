# Separate instruction frames from behavioral content v63

The current contextual encoder receives whole natural-language requests. Test
whether explicit locating instructions add topic similarity without helping
distinguish function behavior. Keep original intent, exact authority, all source6
owners and the complete58 candidate pools/235feature matrix fixed.

The small content_query helper removes ONLY recognized leading EN/ES frames
such as 'Which function that...' or 'Dónde está el método que...'. It preserves
names, quotes, behavioral operators, negation, ordering and unrecognized prose.
Do not remove arbitrary stopwords, function qualifiers or source tokens. Empty
or bare-noun remainders return the original request. Five RED/GREEN tests and
mypy, including negation/order/identifier/underspecification examples.

Using the SAME137M CodeRank graph, tokenizer, query prefix, rawCLS/oneL2 policy,
encode content(original) and content(expanded) once per identical text. All16
source6 contexts58 already exist before requests. Reuse31 query vectors ONLY
for byte-identical query text under identical assets/runtime/pooling, with an
explicit mapping receipt. No source or query sent externally. Unique exact
singleton uses declared neutral context8 placeholders outside model inference.

Compute8 content-context summaries with original full-owner58 source vectors:
raw,to_max,range_relative,reciprocal_rank for each query view. Register TWO fixed
controls: replace old context8 (235columns), or append content8 (243columns).
The original227 source features and original exact/intent semantics do not
change. This tests query representation, not a new encoder or source cache.

Same160tree settings,16whole-repo-excluded fits per control, native/export exact,
same58 eligible_owner targets joined only in evaluator, retrieved-source actual
presenter/64char profilemetadata, ALL400 original strict ALL-anchor references,
strata and budgets. No missing/no-positive case removed and no perrepo tuning.
Compare to58 prepared277strict/291identity; this does not transfer to real API,
public Semble, private acceptance, resource certification or default promotion.

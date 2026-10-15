# Equal evidence must share rank92, one fixed251-feature control

Current source features assign reciprocal ranks by stable argsort, even when
channel scores tie. A measured allzero BM25 channel then gives different votes
according only to proposal order. Context/source-view channels have the same
pattern. This is not another independent observation about source relevance.
Final deterministic proposal-index tie breaking remains appropriate in the
presentation ordering; it must not masquerade as additional channel evidence.

Test one permutation-equivariant rank definition. Descending average rank for
equal scores, reciprocal of that rank; a constant-score channel contributes
zero rank information for all rows. Absolute/raw scores and existing other
relative fields remain untouched. Empty vector yields empty; finite real input
required. Preserve input numeric dtype during unique/grouping, including signed
integer minima, rather than negation or float casting that can merge values.

Use original69 source7/251 matrices and no90action fields. Replace exactly the
nine BASE_FEATURES[:9] *_rank columns and six code/view *_reciprocal_rank columns,
using their existing raw channel values per query. All other236columns and row
order bitexact; all37natural exact bypass rows retain original values. No new
source, encoder, features, NLP runtime or labels. Record ties/constant channels
on all400 and transformation hashes before training; no HPO/alternative formula.

One fixed existing69 LambdaRank160tree/15leaf/min_child40/lambda2/lr.08/trunc5/
seed42/n_jobs1 control with16whole-repo excluded folds and all375training groups
per fold, including original no-positive and exact rows, same69 semantics.
Require independent complete matrix/row/held exclusion review before fit. Exact
native/export equality, original authority/ties/evidence3 and ALL400 references,
strata, ALLanchors,10/40/12000 budgets and errors/missing=zero remain unchanged.
Reproduce baseline286/298; +5strict gate before new actual API profile, no90%
or public win/default/private claim. A math improvement does not by itself
establish a retrieval quality improvement. Preserve negative results.

Primary definition of average tied ranks:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.rankdata.html
The runtime helper uses only NumPy; no new SciPy inference requirement.

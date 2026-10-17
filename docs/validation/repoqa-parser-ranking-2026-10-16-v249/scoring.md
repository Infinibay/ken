# Scoring boundaries to inspect before changing models

This describes the frozen V214/V238/V246 search path, with unchanged production rank weights. It is a navigation aid for the RepoQA investigation, not a claim that all wrong rankings have been explained.

## Source identity is a prerequisite

`parse_*_file` discovers definitions and their source scopes. `index_files` persists canonical identities, enriches bindings where available, and creates owned retrieval passages. `SourceCatalog` authenticates source hashes and determines piece eligibility/containment. A missing parser definition, missing passage or excluded callable kind cannot be rescued by better embedding similarity or a neural reorder of ten existing pieces.

Owned source is exclusive: shorter scopes own nested lines. A parent does not silently inherit a child's implementation. A scope carries signature, documentation, statements and implementation start; missing scope metadata can preserve a valid identity while supplying a poor model input. C++ previously used the symbol-only fallback, with one-line signatures and comments.

## Retrieval has several scores, not one universal similarity

`retrieve` combines exact lookup, lexical retrieval, static identity vectors and static behavior vectors. Reciprocal-rank fusion adds `1 / (60 + rank)` per channel/owner; raw cosine/BM25 signals remain available. Code/identity static vectors use the fixed Potion code encoder. Ranking scores from different families are not probabilities of relevance.

`retrieve_contextual` requests up to 300 owners from the static source path. A distinct expanded query contributes another run only if its text differs. Their union is capped at 600. It then combines the static family, up to 300 full-owner contextual proposals and exact proposals, under a broad cap of 1,200. Most English descriptions have no translation change; do not count identical original/expanded text as independent evidence.

The contextual family uses the maximum of original/expanded cosine similarity. Separate full-documentation contract and owned-implementation vectors already exist, but in this frozen path those separate views enrich proposed owners; they are not additional independent proposal families. This distinction matters when diagnosing an owner that was never proposed.

## Native owner score is a learned tree sum

`EvidenceReranker.rank` calculates a finite feature vector per proposed owner, then `NumericRanker.predict` adds that owner's reached leaf value from every registered tree. Learning rates/forest averaging are already encoded in the serialized leaf values. There is no single fixed weight such as “BM25 × 0.7” to edit.

The registered native forest contains 2,560 trees; the piece forest contains 1,280. Their immutable fingerprints are recorded in `production-rank-models.json`. Numeric prediction executes with NumPy and does not require a training framework.

Inputs include lexical/static/contextual measurements, their ranks and candidate-relative values, name/body overlap, source role, kind, size, term/stem alignment over separate source fields and source shape/operations. Term alignment uses static word embeddings in bounded blocks; source field/query token limits are a distinct budget from the neural reranker's 1024-token pair limit.

Several inputs depend on the whole proposal population. Relative minima/maxima, ranks and term-frequency weights can change when new source owners appear, even if one old owner's code and absolute cosine stay identical. Therefore adding correct parser definitions need not monotonically improve every prior rank. The paired `Id.into_u64` receipt now verifies this effect: 54 additional owners change 42 target feature values and native piece rank 8→outside ten, while the target absolute cosines remain identical. Individual split groups remain interaction accounting rather than isolated causal effects.

An explicit exact identity has priority over model score. Otherwise sorting is by descending numeric score, with the proposal order resolving ties. `RankingTrace` records the actual source identities, feature values and order. Its pair explanation accounts for reached-leaf differences and groups them by the first divergent split. Those are interacting tree-path contributions, not isolated causal feature effects or SHAP values.

## Selecting ten is separate from reranking ten

Native owner matches propose the requested pieces. Symbol eligibility previously excluded constructor/destructor kinds. A class/module/file card represents a different unit from one supporting method; grouping alone must not replace the primary identity.

`PieceSearch` constructs the native top ten and preserves their membership. A piece forest orders these candidates. The neural model scores the bounded source cards. For symbols, `SymbolRanker` may add a whole-owned-code view only when it has at most 64 lines, at most 12,000 characters and fits the reranker's actual pair budget. Otherwise it uses the original card score for that second component. The symbol base order is descending `(card_logit + code_view_logit) / 2`.

Stable preferences for explicitly requested source operations, test entry points and explicit operators can then change that symbol order. `is_test_case` currently recognizes Python/Java entry conventions; source role classification has broader language support, including Rust attributes. Requested file paths have a separate explicit priority. Other piece kinds use weighted reciprocal-rank fusion of existing and neural order. These policies must be evaluated separately rather than attributing every final change to “the embedding”.

The final presentation authenticates the source and returns compact physical code excerpts. No returned ten-item neural stage can recover a relevant owner discarded before the native ten.

## The ceilings are arithmetic

With one reference per query:

`P(top1) = P(reference in top10) × P(selected first | reference in top10)`.

The closed Rust parser-only result is `0.59 = 0.90 × 0.6556`. At 90% top-10, reaching 90% top-1 would require perfect selection among available references. At 95% top-10, 90% top-1 still requires about 94.74% conditional selection. Both proposal retention and final selection must improve; the former cannot be inferred from success on a different benchmark.

## Required failure ledger

For every strict miss, preserve the same original query/reference and distinguish:

1. Reference anomaly or ambiguous description, documented without extra credit.
2. Definition missing/malformed in parser output.
3. Definition parsed but missing from the indexed owner/passages.
4. Indexed but ineligible as the requested piece.
5. Eligible but absent from the combined proposal pool.
6. Proposed but absent from native ten after numeric ranking/grouping.
7. In native ten but reordered below first by piece/neural/symbol policy.
8. Correct first: a control case for regression checks.

For stage 5 inspect independent family ranks and source text budgets before replacing an encoder. For stage 6 compare actual feature/tree paths, query role and source contracts. For stage 7 compare card/code logits, fit decisions and later preferences. Preserve membership and code identity while making each comparison.

## Source feature omissions to keep distinct from model error

`describe_owner` currently derives executable lines with a shared comment-start regex. A line beginning `*` or `--` can be C++ executable code, yet it is removed from executable/calls/returns features. The authenticated implementation view preserves those bytes. Rust implicit tail returns also do not match the explicit return/throw/raise/yield regex. These are source projection gaps with synthetic reproductions, not evidence that the embedding itself cannot express the operation. Fixing them should preserve language-specific comment semantics and avoid changing raw source/evidence.

The contextual runtime intentionally uses CPU, batch size one, no padding and a 512-token prefix budget. Its document cache keys include exact model policy and source-view text. Reusing this content cache across parser variants does not reuse relevance labels or query results. Altering batching, pooling, quantization or text construction requires an explicit policy/cache change and numerical and retrieval comparisons; silently reusing old vectors would invalidate the experiment.

## Closed C++ failure attribution and the V258 correction

V246 provides 97 matching indexed owners and all 97 reach proposals. Three strict misses lack a canonical matching indexed identity; nine are lost during numeric native-ten selection; 21 remain in ten but miss first. Raw contextual symbol order scores66first/89inten, native symbol grouping57/88, neural card67/88, code68/88, equal mean69/88, old final preferences67/88. These separate measurements explain why replacing one embedding cannot be inferred to solve all failures.

The explicit operator preference wrongly treats named bitwise AND/OR as a demand for boolean keyword witnesses. `roundDownPageBoundary` and `make_mask` are first in every measured semantic/numeric order but are demoted by that rule. V258 keeps the model's order when bitwise semantics cannot be established by that boolean witness. A closed100-case post-model replay gains exactly these two, loses none and retains every top-ten member. This replay introduces no new logits or performance measurements. The same requirements inputs are unchanged on the historical400 public development queries; no reserve is opened.

For `copy_inplace_dispatch`, contextual symbol rank5 versus static family59 becomes native owner26; actual tree interaction accounting against chosen `copy` assigns −1.7818 of the −4.1544 margin to trees first diverging on `rrf_rank`. This is evidence to investigate proposal-consensus priors and complete signatures, not a standalone feature coefficient or proof that globally suppressing RRF improves unseen repositories.

## Rust direction and role examples

All100Rustreferences reach broad proposals. Ten are lost before native10,31after retention; no missing embedding proposal explains them. Contextual symbol order67/93 exceeds native58/90; whole-code neural64, card61 and their arithmetic mean59 first-place hits on the same native10 show the two view logits are not a universally sound equal-quality scale. Do not replace the current policy from this diagnostic alone; the old English development suites still gate any change.

For `i16_tests`, query-purpose inference marks implementation, although its first purpose sentence describes testing. The native pair margin against `bits` is−3.0610, with−3.0309 first-divergent role-match interaction accounting. This locates a role inference/data issue; it does not justify a benchmark-ID test preference, treating every runtime validation as a test, or retraining on the same evaluation labels.

The closed two-language composition portfolio records every variant, gains and losses. It changes no production default and no native-ten membership. The separately registered20candidate/single-view experiment tests whether preserving contextual proposals can recover native selection losses within the existing maximum20neural-pair budget. Keep strict function identity, all100questions, code/source integrity and CPU/RAM measurement; do not report diagnostic union/oracle values as achievable accuracy.

## Composition and portability regression evidence

Using only whole-code neural scores improves the closed Rust pool but lowers prior English development from 218/240 to 214/240. Fixed card/code reciprocal-rank fusion and within-query standardized mean each obtain217/240. All240baseline identity orders reproduce before grading. These fixed, label-free formulas are therefore rejected as production defaults from this evidence. No parameter is fitted and no private reference is inspected. Candidate-retention experiments must still protect these earlier cohorts.

Retained pair vectors contain every actual numeric input, not just the largest feature groups. All145saved scores reproduce exactly. Keep those vectors and full original traces when investigating a new proposal/representation policy: a number such as `rrf_rank` is a dependent observation about a candidate population, and removing one feature after seeing one miss is not a validated ranking design.

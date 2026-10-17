# RepoQA retrieval audit and parser corrections — 2026-10-16

This is a public development diagnostic using the original 600 English RepoQA descriptions, 60 shipped repository snapshots and six code languages. The private acceptance reserve remains closed. No release is made, no model weights are fitted, and original queries, references and grading criteria remain unchanged.

## What the measurement means

The frozen initial engine obtains **415/600 top-1 (69.17%)** and **497/600 top-10 (82.83%)**. The independent review reproduces all 600 cases, the selection of the sole preregistered infrastructure retry, 6,000 result slots and 7,119 faithful source excerpts. It finds no C++/Rust prediction rejected solely by a name or coordinate normalization discrepancy. See [measurement review](independent-measurement-v236.json).

A hit requires the exact reference path, function leaf name, eligible callable kind and definition end. The returned start may precede the reference start by at most ten lines for decorators/templates. Class/file containment alone earns no function credit. The variant evaluator separately verifies physical source hashes, freshness and every literal excerpt before applying that unchanged relevance helper. Errors remain in the denominator. This is a function-identity retrieval proxy, not RepoQA's official long-context LLM SNF score, and these exposed public queries are not a blind acceptance set.

Three original C++ identities are noncanonical: a catch block, a macro loop invocation and a constructor initializer recorded as `m_path`. They remain in the original denominator and are not renamed into convenient function labels. Exact agreement with these original labels is not proof of canonical C++ identity. The independent review also documents limitations of the historical scorer; none changes the reconstructed historical numerator.

## Separate failures before blaming embeddings

| Code language | Reference identities parsed/indexed/with passages initially | Initial top-1 | Initial top-10 |
|---|---:|---:|---:|
| C++ | 50/100 | 35/100 | 43/100 |
| Rust | 87/100 | 53/100 | 80/100 |
| Python | 100 indexed/with passages | 80/100 | 92/100 |
| Java | 96/100 | 78/100 | 89/100 |
| TypeScript | 100 indexed/with passages | 83/100 | 99/100 |
| Go | 100/100 | 86/100 | 94/100 |

Python and TypeScript's legacy symbol-only parser inspection finds 96/94 identities; their enriched scopes already place all 100 in the actual index and retrieval passages. Do not report those as index omissions. C++ and Rust have actual omissions at all three boundaries. Zero parser exceptions explain the missing C++/Rust reference functions in this initial reference-file audit.

C++ cumulative source extraction checks, with the same 100 reference identities:

| Isolated correction | Matched reference identities |
|---|---:|
| Initial | 50 |
| Traverse every conditional preprocessor branch without evaluating flags | 65 |
| Resolve `.h` from C++ syntax; preserve plain C | 80 |
| Visit nested types wrapped by field declarations | 87 |
| Recover namespace headers confused by preceding macros | 95 |
| Discover local types under their enclosing callable | 96 |
| Keep friend functions in their enclosing namespace | 97 |

No previously matched reference is lost by these extraction steps. The 97 is reference-label coverage, not a search accuracy claim or a claim that all labels are canonical. The remaining three unmatched labels are the catch/macro-loop anomalies and an MLX constructor hidden by a tree-sitter ERROR around unexpanded declaration macros. The separate `m_path` anomaly already agrees with an erroneous parser identity and must not be treated as evidence of a correct constructor model.

Rust's twelve implemented trait defaults plus one local function were omitted. Defaults now retain the trait as lexical owner; local functions retain the enclosing callable and remain functions rather than methods. Coverage goes 87→99→100. Bodyless trait signatures remain declarations rather than invented implementations.

Constructors and destructors also had a second problem: their source identities could exist in the index but `SourceCatalog.primary(..., 'symbol')` excluded them. They now compete as native callable pieces. This is independent from embedding quality.

## Closed Rust result: parser changes only

The 100 original Rust requests are recaptured using the frozen [V238 engine manifest](rust-engine-manifest-v238.json), with identical models, ranking weights, ten slots, 12,000 characters and 1024 reranker tokens. Preparation uses supported `retrieval index` followed by `retrieval prepare`. See [closed report](rust-report-v239.json).

| Metric | Initial | Parser correction |
|---|---:|---:|
| Correct function top-1 | 53/100 | **59/100** |
| Correct function top-10 | 80/100 | **90/100** |
| Correct file top-1 | — | 81/100 |
| Correct file top-10 | — | 97/100 |
| Indexed reference with passages | 87/100 | 100/100 |
| Query errors | 0 | 0 |

Six first-place gains, zero first-place losses; eleven top-10 gains and one loss. The remaining failures are **31 correct functions inside ten but not first, and ten outside ten**. The lost top-10 case is `Id.into_u64`, ID `86a2e6c50b5263a4c119cd96`; the paired source/model comparison below now locates that regression. It does not isolate each parser slice's effect.

All 1,000 returned slots and 1,184 excerpts pass source-integrity checks. Observed prepared-index query p50 is 3.261s, p95 4.843s and maximum 6.381s; peak query process RSS is 1,304,231,936 bytes (1.215GiB). Both contextual encoder and reranker attest CPUExecutionProvider; no torch/transformers imports. These are observed timings with concurrent development/benchmark activity, not an isolated speedup claim. Preparation and model warmup are excluded from query latency and retained separately.

The independent [review of all 41 Rust misses](independent-rust-references-v248.json) classifies 30 clearly wrong first results, four operation-equivalent pairs, five material query/reference mismatches and two uncertain cases. For example, `nom::yd` delegates to the same streaming digit parser returned first; a Helix reference is a unit test whose description instead specifies the `ChangeSet::compose` implementation returned first. Conversely, `TokenSource::tokenize` and `split_on_newline` return different kinds of values and are not equivalent. **No alternative credits are added to the 59/100.**

## Closed C++ result: coverage and callable eligibility

All 100 original requests close without query or stage-replay errors. With the [V246 frozen engine](cpp-engine-manifest-v246.json), unchanged model weights and original exact-function criterion, top-1 increases **35→67/100**, top-10 **43→88/100**. There are 32 first-place gains, 45 top-10 gains and zero losses at either threshold. All 97 parsed reference labels have indexed passages. See [complete report](cpp-report-v246.json).

The 1,000 returned slots and 1,107 excerpts pass source authentication. Observed query p50 is 3.186s, p95 4.511s and maximum 5.643s; query process peak RSS is 1,266,925,568 bytes (1.180GiB), CPUExecutionProvider only. Preparation and diagnostic replay are separate from these measurements; concurrent activity prevents an isolated speedup claim.

The [100-query stage ledger](cpp-stage-ledger-v257.json) locates the 33 strict misses: three missing/noncanonical identities, nine proposed reference owners discarded before native ten, and 21 retained in ten but not first. **Every one of the 97 indexed reference labels reaches the combined proposal pool.** A general claim that those references are absent because the embedding cannot retrieve them is contradicted by this capture.

| C++ order observation | Correct first | Correct in ten |
|---|---:|---:|
| Raw full-view contextual similarity, symbol-eligible owners | 66 | 89 |
| Static proposal family | 31 | 69 |
| Native owner order after symbol grouping | 57 | 88 |
| Neural source-card scores inside the same native ten | 67 | 88 |
| Neural whole-code scores inside the same native ten | 68 | 88 |
| Equal mean of the two neural views | 69 | 88 |
| Final historical policy after hard preferences | 67 | 88 |

These are stage observations, not independent full benchmark variants. The neural stage makes 16 native first-place promotions and six losses, net +10. Two full-view contextual top-ten targets (`copy_inplace_dispatch`, `uv_token`) are discarded by native selection. The [numeric pair receipts](cpp-numeric-pairs-v263.json) expose exact feature values and reached-tree margins: the `copy_inplace_dispatch`/`copy` pair has native margin −4.1544, with −1.7818 grouped under the first divergent `rrf_rank` split. Its contextual symbol rank is five, static family rank 59 and native owner rank 26. This suggests excessive reliance on cross-channel agreement for this pair, **not an isolated causal coefficient or authorization to erase the RRF feature**.

Two correct first results are demoted solely by the explicit-operator preference. Queries name bitwise AND/OR, but the old lexical witness recognizes boolean keywords and `&&`/`||`, not bitwise semantics. The correction avoids imposing that unsupported boolean preference. Three synthetic regressions fail before the fix and pass after it; normal boolean-keyword preferences remain covered.

A separately closed deterministic [policy replay](bitwise-replay-report-v261.json) reuses the exact same native ten, logits and authenticated source, then applies only that final-rule correction across all 100 C++ queries: **69/100 top-1, 88/100 top-10**, two gains and no losses. This is not a fresh model-inference, latency or RAM measurement, nor a combined full-contract engine capture. Its guard inputs are also identical on all [400 previous public development queries](bitwise-old400-guard-check-v261.json); this verifies only this policy slice, not every parser/constructor change in the current engine.

## Closed Rust stages and independent C++ review

The [Rust replay](rust-stage-ledger-v266.json) reproduces all 100 closed normal result-identity sequences without stage errors. All 100 indexed reference functions reach combined proposals: ten are discarded before native ten and 31 remain in ten below first. Raw contextual symbol order gives67first/93inten; native symbol grouping58/90; card neural scores61/90; whole-code neural scores64/90; their current equal mean59/90. Averaging these two logits is therefore not reliably better than either view on this set. It is not a calibrated probability combination.

Actual [Rust tree pairs](rust-numeric-pairs-v267.json) show `i16_tests` at contextual rank3 but native rank23. Against the chosen `bits`, the native margin is−3.0610; trees first diverging on `role_match` account for−3.0309. The query describes testing but is inferred as implementation, making the test owner's feature0 and the implementation's1. For `be_i8_tests`, contextual rank1 becomes native19; both RRF rank and role-match paths contribute negatively. These are actual path interactions, not standalone causal coefficients. `Id.into_u64` is contextual rank8, static84 and native20; the existing trace shows the loss occurs before neural reranking. The paired pre/post-parser diagnostic below verifies unchanged absolute cosine and changed owner population/rank features; it does not isolate each individual parser correction.

The independent [C++ review](independent-cpp-references-v259.json) reads all33strict misses and both complete source bodies:15clearly incorrect top1s,3operation-equivalent pairs,12query/reference mismatches and3ambiguous cases. Ten mismatch descriptions attribute a class's later operation to a constructor; two references are noncallable grammar artifacts. One equivalent case returns a forward declaration of exactly the same C++ callable whose body the reference selects (`doAdvicesChain`); the proxy distinguishes them by end line. None earns alternative credit. Some mismatched top1s also fail the description: do not automatically substitute the returned item for a defective reference.

The source-only comment-projection audit finds [six C++ reference bodies](cpp-discarded-source-v268.json) with19noncomment directive lines excluded from executable features; five already hit first and the sixth is the bitwise preference defect. [Two Rust bodies](rust-discarded-source-v269.json) lose four cfg attributes and both already hit first. The synthetic pointer-write/decrement bug is real, but no such lost pointer/decrement line occurs in these reference bodies. This distinguishes a confirmed source-quality defect from a demonstrated explanation of the remaining benchmark failures.

A fixed [composition replay](view-consensus-replay-v272.json) keeps native-ten membership and frozen logits across all200closed C++/Rust cases. After the bitwise correction, the existing mean gives128/200first; code-only132; equal RRF of contextual and mean orders135; promoting agreement between global contextual and complete-code first candidates133. Existing explicit source requirements are preserved in every arm. The RRF arm loses one net point in C++ (69→68), while agreement gives C++70/Rust63. **None reaches90%, none has prior-development regression acceptance, and none is installed as a new default.** These are exposed development comparisons, not fresh neural inference or blind acceptance.

The next [candidate/view experiment](candidate-view-experiment-v274.md) keeps native10plus contextual10 unique symbols (at most20), supplies one complete-code-or-atomic-card view per owner to the same CPU model, and returns ten. It compares a native10single-view control using the same logits. This tests the native-ten selection bottleneck without raising the maximum neural pair count beyond the current two-view ten-candidate budget. It remains research code until complete capture, unchanged grading and previous English-development regression checks.

## Preparation defect and migration

The first V238 attempt failed every group during a fixed unrelated warmup, before any original benchmark question was evaluated. `retrieval prepare` passed an explicit default PassagePolicy to `index_files`, which bypassed active projection maintenance during a parser-version reindex. The profile fingerprint remained current, so `_projection` did not fill the deleted identity vectors. This is an indexing/preparation defect, not evidence of poor retrieval on those questions.

The failed attempt is retained. A preregistered infrastructure retry performs normal `retrieval index` then `prepare`, with the same frozen engine, models and original requests. The production prepare command is separately corrected to honor the active projection, with a real SQLite parser-upgrade reproducer that fails before the fix and passes after it. Parser versions invalidate unchanged files when extraction or scope contracts change.

## Input quality and ranking hypotheses still under test

C++ previously supplied the first source line as signature and the first comment line as documentation. Complete C++ scopes now preserve full multiline/template signatures, full preceding documentation, statements and the actual implementation start. Every symbol kind must receive a scope: once `parsed.scopes` is nonempty, passage extraction intentionally does not use the legacy symbol fallback. A synthetic test covers a templated member plus class, enum and alias so this migration cannot silently erase noncallable owners. This representation change is isolated from the C++ coverage capture and still needs its own ranking comparison.

Discovery of local declarations uses iterative expression walks; both parsers now handle valid expressions containing 1,500 operands without a RecursionError that would otherwise drop the entire file. A [source-only parity check](iterative-parser-parity-v256.json) verifies unchanged parsed dataclass output on all 1,887 C++/Rust corpus files (1,263/624 respectively), with zero parser exceptions.

The [role audit](role-intent-summary-v250.json) finds 15 initially indexed Rust test-role targets, with only five first-place hits. Twelve queries explicitly mention testing/assertions, yet no target query is interpreted as test intent. `interpret` primarily understands imperative search instructions; the benchmark descriptions are declarative. `is_test_case` recognizes Python/Java entry conventions but not Rust attributes, although passage role classification recognizes Rust tests. This is a concrete mismatch to investigate, **not yet a demonstrated causal fix or license for a benchmark-specific regex**.

C++ V246 closed all 100 requests plus untimed stage observations. Rust V251 has replayed all100closed V239 identities through the same frozen engine after C++ closed; every identity sequence reproduces. Both workers receive original requests and source-only caches, never reference labels. They retain complete contextual similarities, proposal signals, numeric tree inputs/order, native cards and final neural/code-view scores. Diagnostic replays must reproduce normal result identities. Do not grade or tune from partial captures.

## Embedding hypothesis: checks and remaining uncertainty

The contextual encoder is CodeRankEmbed INT8 in ONNX Runtime. Its official [model card](https://huggingface.co/nomic-ai/CodeRankEmbed) requires the query prefix `Represent this query for searching relevant code: `; Ken applies it. The official [pooling configuration](https://huggingface.co/nomic-ai/CodeRankEmbed/blob/main/1_Pooling/config.json) selects CLS pooling rather than mean pooling; Ken extracts CLS and explicitly normalizes in retrieval. These checks find no obvious prefix/pooling mismatch. They do not establish that the encoder ranks every target well.

The pinned quantized artifact has SHA256 `4eae31d09b1843103a1ebd5e2b2e24b5a5cad441a33906b35b12b1e2ed91d1db`. Its local pinned primary README identifies the corrected per-channel, reduced-range INT8 export. An existing label-free native/export parity receipt at `output/analysis/coderank-native-parity-v21/report.json` uses these same base and export revisions: nine nonempty probes have approximately 0.965–0.978 native/export cosine agreement; an empty two-token probe has 0.867. Quantization is not mathematically identical, but these small probes cannot attribute RepoQA errors to quantization or prove it harmless. No replacement encoder is selected from them.

A tokenizer-only audit uses the original 100 queries and indexed reference source views. See [Rust budgets](rust-embedding-budgets-v254.json) and [C++ budgets](cpp-embedding-budgets-v254.json). No model is executed and no label is fitted. All queries fit the contextual encoder's current 512-token policy: maximum 327 tokens in Rust and 345 in C++, including the required query prefix. Eight Rust full-owner views exceed 512 tokens; two of the 97 indexed C++ reference views do. Separate contract/implementation views also have their own budgets. Thus query truncation does not explain these misses; source truncation remains a possible cause for a subset. A [join with closed quality reports](budgets-and-errors-v265.json) finds that 40 of 41 Rust misses have full views within 512 tokens; seven of eight over-budget Rust views still obtain top-1. Both over-budget C++ targets miss top-1, one remains in ten. These associations do not prove truncation causality. The upstream architecture's larger context capacity does not mean Ken currently runs that capacity or that increasing it has acceptable CPU cost.

Three synthetic [projection reproductions](projection-information-gaps-v253.json) expose additional information gaps, not yet production corrections: a language-agnostic comment regex treats C++ pointer writes and decrements as comments; implicit Rust tail returns do not enter the `returns` field; multiple definitions on one physical line can lose child-owned passages under line-only ownership. Original implementation text still exists in the first two cases, so feature loss must not be confused with complete source loss. None is assigned a measured accuracy gain before an isolated comparison.

## Closed regression diagnostics and retained evidence

The [paired `Id.into_u64` comparison](rust-owner-population-comparison-v284.json) holds the original query, source bytes and models fixed. Parser coverage adds 54 source owners (364→418); the target's full contextual cosine remains exactly 0.39385074377059937 and both static cosines remain unchanged. Its contextual symbol rank changes 4→8 and native piece rank 8→outside ten. Three new proposals rank ahead of it, and two old proposals overtake it. Forty-two target feature values change, reducing its native score by 0.2126384. This demonstrates a population-sensitive ranking regression despite unchanged absolute target similarity. It does not assign independent causality to one split or one parser slice.

The [complete wrong-first pair export](failure-pair-features-v286.json) retains all 251 numeric features for both owners in 71 complete C++/Rust pairs. Three unmatched/noncanonical C++ reference rows retain a null gold owner. [Recomputation](failure-pair-feature-verification-v289.json) reproduces all 145 saved scores exactly against the bundled forest, including those three chosen owners. The C++ observations precede complete contracts and the bitwise correction. Full population traces remain in the local experiment output; pair features reproduce pair margins, not an absent full-population order.

A separate [fixed composition replay over all 240 prior exposed English queries](old240-view-scale-report-v290.json) reproduces every baseline order before reading the already consumed references. Original/new-symbol cohorts each retain 120 questions. Existing mean obtains 110/108 first-place hits, code-only 109/105, fixed reciprocal-rank fusion 110/107 and query-standardized mean 110/107. Top-ten counts remain 118/119 in every arm. These negative regression results block promoting a code-only or uncalibrated fusion default from the Rust-only gains. No fitting, new inference, reserve access or fresh latency claim is involved.

The [actual runtime input audit](runtime-budgets-v280.json) checks the closed 200 C++/Rust calls: no source card or accepted complete-code pair is truncated by the reranker's 1024-token policy. Every retained reference owner has an accepted complete-code view. Query-term limits also do not truncate any request (maximum 95/109 terms versus 128). The [complete C++ contract token audit](cpp-complete-contract-budgets-v279.json) preserves the source-budget counts: two of 97 full reference views exceed the separate contextual encoder's 512-token policy. Those are different models and budgets.

The published [Potion model card](https://huggingface.co/minishlab/potion-code-16M-v2) and [CoRNStack paper](https://arxiv.org/html/2412.01007v1) describe code contrastive training in Python, Java, JavaScript, Go, PHP and Ruby. C++ and Rust are absent from that listed training corpus. Language/domain shift is therefore a plausible embedding hypothesis, **not a measured attribution of these RepoQA misses**. It also does not establish absence from the encoders' broader pretraining. Ettin's [68M model card](https://huggingface.co/cross-encoder/ettin-reranker-68m-v1) specifies a larger architectural input maximum; Ken intentionally uses a 1024-token CPU profile and these captured pairs fit it.

## Verification and boundaries

The [complete verification receipt](verification-v291.json) records **15,042 passed and ten pre-existing expected failures**, with the existing type-check gate clean on 361 source files. The relevant parser, indexer and retrieval suites also pass independently. Header-selection changes also pass inspection/responsibility tests. New behavior regressions were observed failing before implementation, including trait defaults, local owners, guarded declarations, ambiguous headers, constructor eligibility, projection upgrades, complete C++ contracts and deep expressions.

The original dirty checkout's 63 foreign files are preserved byte-for-byte. Product work is isolated in the attached managed worktree. Historical and new registrations, immutable engine manifests and original producers are retained under the local experiment workspace; exact producer copies below retain their original local import paths for auditability. They are historical receipts rather than a promise of relocation without registering new paths/hashes.

The original 600-case grading helper is unchanged. No private acceptance query is inspected, no model is trained on these 600 evaluation labels, no benchmark-specific repository/name/ID branch enters production, and no release is made. **The 90% top-1 objective is not yet demonstrated.**

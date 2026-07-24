# Ranker improvement plan

## Implementation status (2026-07)

| Phase | State | Notes |
|-------|-------|-------|
| 0 — eval harness | **done** | `examples/bench/eval/` (miner + version-agnostic harness + diff). nDCG@8/recall@8/MRR/hit@8, held-out mined labels. |
| 1 — log-odds fusion | **done, opt-in** | `src/ken/ranker/fusion.py`, behind `KEN_RANKER_FUSION=logodds`; legacy remains default (byte-identical regression-checked). |
| 3 — lift/PMI | **done, opt-in** | `channels.base_rate_discount` applied in predictive + cooc, behind `KEN_RANKER_LIFT=1`; default off. |
| 4 — PPR | **done, opt-in, additive** | `src/ken/ranker/ppr.py`, `KEN_RANKER_PPR=add`. Validated as an *additive* channel with git co-change ingested — NOT as a replacement, and NOT without co-change (both measured negative). Default off. |
| 2 — multilingual + adaptive | **done, opt-in** | Embedder swap via `KEN_EMBED_MODEL` (existing) + adaptive thresholds (`channels._adaptive_threshold`, `KEN_RANKER_ADAPTIVE=1`). Multilingual model is a language-dependent tradeoff (big Spanish win, English cost); adaptive is a calibration compensator. Both default off. |
| 5, 7 | pending | — |

Measured vs baseline (frozen index of this repo; see harness). Flags are
independent; `logodds+lift` is both on:

| set | metric | baseline | lift-only | logodds+lift |
|-----|--------|----------|-----------|--------------|
| curated (6, full DB) | mrr | 0.889 | 0.889 | **0.917** |
| curated | ndcg@8 / recall@8 | 0.659 / 0.681 | 0.659 / 0.681 | 0.658 / 0.681 |
| mined (15, held-out) | ndcg@8 | 0.124 | 0.147 (+19%) | **0.148 (+19%)** |
| mined | mrr | 0.128 | 0.155 (+21%) | **0.167 (+30%)** |
| mined | recall@8 | 0.178 | 0.178 (=) | 0.167 (−0.011) |
| mined | avg_tokens | 51 | — | **45 (−11%)** |

Read:

- **Phase 1 (log-odds fusion)** lifts top-ranked precision (MRR up on both
  sets) and orders the hard held-out set better (nDCG +12%), at a small
  recall cost on the hard set; neutral on the clean set. The load-bearing
  fix was grouping all name/text-derived channels (fuzzy-file, doc-intent,
  lexical, literal) into ONE noisy-OR family so they can't spuriously
  corroborate across the log-odds sum.
- **Phase 3 (lift/PMI)** is a near-Pareto win: on its own it improves the
  hard set (nDCG +19%, MRR +21%) with **zero cost on the clean set and no
  recall loss**, by discounting files by their global base rate so ubiquitous
  files (`cli.py`, `db.py`) stop accruing predictive/cooc evidence for every
  prompt. Combined with Phase 1 it gives the best ordering overall and also
  trims context size 11% (fewer ubiquitous files padding the block).

All three remain opt-in behind flags; the legacy default is regression-checked
byte-identical to pre-change.

### Phase 4 (PPR) — what the measurement changed about the design

The plan proposed PPR to *replace* the import/test/cooc boosts. Measurement
(via the harness) rejected that and refined it:

- **Replace mode is negative.** Folding the precise, name-exact test-affinity
  into a generic graph walk loses precision the sparse graph can't recover —
  worse than baseline at every tuning (curated nDCG 0.62 vs 0.66).
- **Co-change is required.** Without `cr_commit_files` edges (older DBs, or
  before `ken_cochange` runs) PPR has too little graph to help.
- **Additive + co-change + gentle tuning is a clean win.** Keeping the precise
  boosts and *adding* PPR only for the multi-hop + git-co-change structure they
  miss: curated fully preserved, mined recall 0.178 → **0.211** (+19%). Full
  stack (logodds+lift+ppr-add) on a co-change-enriched index: mined nDCG
  0.124 → **0.168** (+36%), recall → 0.200 (+12%), MRR → 0.167 (+30%);
  curated MRR 0.889 → 0.917.

Defaults in `ppr.py` are set to the gentle additive values; `KEN_RANKER_PPR=add`
is the validated mode. Requires co-change ingested (`ken_cochange`) to be worth
enabling.

### Qualitative spot-check (real queries, old vs new stack)

Running the ranker on hand-written queries against the co-change-enriched ken
index surfaced things the aggregate metrics hid:

- **Wins:** clearer score separation; new stack surfaces genuinely relevant
  files the baseline missed (e.g. `snapshot.py` for "predictive scores",
  `boosts.py` for "penalize dismissed files") via lift + PPR.
- **Regression to fix (Phase 1 follow-up):** on "where is X implemented"
  queries the logodds calibration lets an exact-name-matching test file
  (`test_fuzzy.py` for "fuzzy … computed") edge just above its implementation;
  `apply_implementation_intent`'s ×0.45 test demotion is under-calibrated for
  the logodds scale. The aggregate metrics miss this because their gold sets
  include tests.
- **Open gap → Phase 2:** Spanish "where is X" queries (e.g. "dónde se aplica
  el decay por turno") are suppressed by the confidence gate in *both* versions
  — the absolute cosine thresholds + English embedder drop all similarities.
  This is exactly Phase 2's target.

### Phase 2 (multilingual + adaptive thresholds) — measured

Re-embedded the corpus with `paraphrase-multilingual-MiniLM-L12-v2` (384-dim,
drop-in via `KEN_EMBED_MODEL`, no schema change) and re-ran the harness. The
multilingual model is a **language-dependent tradeoff**, not a free win:

| config | curated (English) | mined (Spanish, held-out) |
|--------|-------------------|---------------------------|
| MiniLM-en + baseline | ndcg 0.659 / rec 0.681 / hit 1.00 | ndcg 0.124 / rec 0.178 / hit 0.27 |
| multilingual + full stack | ndcg 0.499 / rec 0.528 / hit 0.83 | ndcg **0.198** / rec **0.256** / hit 0.33 |
| multilingual + stack + adaptive | ndcg 0.568 / rec 0.611 / hit **1.00** | ndcg 0.147 / rec 0.183 / hit **0.40** |

Read:

- **Multilingual embedder** is a large win on the user's actual (Spanish)
  prompts — mined nDCG +60%, recall +44%, MRR +75% with the full stack — but
  costs English retrieval (curated recall 0.681 → 0.528), since a multilingual
  MiniLM is weaker on pure-English code than the English-specialised one.
  Recommend it as the default *for non-English users*, documented as a
  tradeoff; it is already a one-env-var swap.
- **Adaptive thresholds** are a *calibration compensator*: they recover the
  multilingual model's English (curated hit@8 0.83 → 1.00, nDCG 0.50 → 0.57)
  because the fixed 0.40 floor is mis-tuned for its shifted cosine
  distribution — but they *hurt* the well-calibrated MiniLM-en (adds noise,
  larger blocks). Keep behind `KEN_RANKER_ADAPTIVE`, off by default; enable
  only alongside a non-default embedder.

There is no single dominant config — it is a Pareto frontier over language mix.
For this Spanish-writing user, `KEN_EMBED_MODEL=…multilingual… + full stack +
adaptive` is the best balance (English recovered to hit@8 1.0, Spanish hit@8
best-of-all at 0.40).

### `ken reembed` — swapping the embedding model safely

Changing the embedding model invalidates every stored vector, but ken keeps
the *source text* of every embedding in plain text (prompts in
`cr_contexts.content`, docstrings in `ci_intent_sources.text`, symbol
name/kind/docstring in `ci_symbols`, file text derived from `ci_files` +
its symbols). So re-encoding never needs the worktree or a re-parse:

```sh
ken reembed                      # re-encode with the current model
ken reembed --model BAAI/bge-small-en-v1.5   # switch model
ken reembed --check              # verify stored vectors match the live model
```

**Model name is not a sufficient identity check.** The same name can produce a
different vector space across library versions — fastembed switched
`paraphrase-multilingual-MiniLM` from CLS to mean pooling, which silently
changes every vector. So `reembed` also stores a **probe**: a fixed sentence
and its encoding (`embed_probe_text` / `embed_probe_vec` in `meta`).
`--check` re-encodes the probe and compares cosine against the stored vector.

This catches cases a dimension check cannot: `bge-small-en-v1.5` has the *same*
384 dimensions as the current MiniLM, yet the probe cosine between them is
**0.21** — instantly flagged as stale.

### Not done: Phase 5 (learned weights) & Phase 7 (FTS5/BM25F)

- **Phase 5** needs months of `cr_exposures` data (Phase 0 logging just
  started) to fit weights honestly — deferred by design, not skipped.
- **Phase 7**: the FTS5 table (`fts_files`) already exists for `ken_grep`;
  wiring the literal/lexical channels onto it is independent cleanup, not
  blocking the algorithmic phases.

---

Status: proposal (2026-07) for phases 2–7. This is the implementation plan for
upgrading the context-rank algorithm's math, derived from an analysis of the
current ranker (`src/ken/ranker/`) and of comparable systems (Aider's
repo-map / personalized PageRank, hybrid BM25+dense+RRF retrieval stacks,
implicit-feedback learning-to-rank).

Guiding constraints, in order:

1. **Local-first stays non-negotiable.** Everything runs on-device against
   `.ken/ken.db`; no network calls, no heavy models by default.
2. **Rank latency budget unchanged.** `rank()` is called inline on every
   UserPromptSubmit; today it is single-digit ms plus the literal channel's
   IO. Nothing in this plan may make it slower than it is today (several
   phases make it faster).
3. **Behavioral memory is the moat.** The reactive → snapshot → predictive
   cycle and dismissal evidence are what no comparable tool has. Phases are
   ordered to protect and sharpen that signal, not dilute it.
4. **Every phase lands independently.** Each phase has its own flag, its own
   bench evidence, and can ship (or be reverted) alone.

---

## Phase 0 — Evaluation infrastructure (prerequisite for everything)

**Problem.** The ranker has ~60 hand-tuned constants and a 6-case bench
(`examples/bench/ken-dogfood.jsonl`). No change below can be accepted or
rejected honestly without a larger labeled set and standard metrics.

**Work.**

- **Implicit-label miner.** New module (proposed: `src/ken/bench/labels.py`)
  that walks `cr_sessions` / `cr_contexts` / `cr_interactions` and emits
  `(prompt, relevant_files)` pairs, where relevance = files with `edit`,
  `write`, or `cited` events in the turns following that prompt. Graded
  labels: edited/cited = 2, read-and-kept = 1. Exclude prompts with no
  follow-up activity and continuation prompts ("sigue", "continue") whose
  intent lives in a prior turn (reuse `_CONTINUATION_RE`).
- **Metrics in `ken bench`.** Extend the bench CLI to report nDCG@8,
  recall@8, and MRR alongside whatever it reports today, over both the
  curated JSONL and the mined set. Persist per-run results so regressions
  are diffable.
- **Exposure logging (start collecting now, consume in Phase 5).** Record
  which targets each rendered `<context-rank>` block actually contained:
  new table `cr_exposures (context_id, target_kind, target, score, rank)`,
  written where the daemon renders the block. Costs nothing today; Phase 5
  is impossible without months of this data.

**Acceptance.** Bench runs over ≥100 mined cases on this repo's own history;
baseline metrics recorded for the current ranker. No ranker behavior change.

**Risks.** Mined labels are biased toward what past ranking surfaced (the
feedback loop this plan later corrects). Acceptable for regression testing;
flagged clearly so nobody tunes *to* the mined set alone.

---

## Phase 1 — Calibrated fusion: from hand-tuned magnitudes to log-odds

**Problem.** Channels emit scores on incompatible ad-hoc scales (explicit
5.0, fuzzy ≤4.5, literal ≤2.5, lexical ≤~1.4) and `merge.py` compares them
directly, with a constant +0.5 synergy per extra channel. Corroboration
magnitude is ignored; correlated channels (fuzzy-file, doc-intent, lexical —
all derived from names/docstrings) double-count; the dismissal penalty is a
subtraction on an arbitrary scale; `MIN_CONFIDENCE = 1.5` is a magic number
on that same arbitrary scale.

**Design.**

- Each channel maps its raw signal through a per-channel calibration
  sigmoid `P_c = σ(a_c · signal + b_c)` interpreted as "probability this
  target is relevant given only this channel". Initial `(a_c, b_c)` chosen
  to reproduce today's effective ordering (fit against Phase 0 baseline so
  the switch is behavior-neutral-ish on day one); refined from data in
  Phase 5.
- Fusion is additive in log-odds: `score(t) = Σ_c w_c · logit(P_c)` with
  per-channel weights `w_c`. Channel families (semantic: fuzzy/doc-intent;
  lexical: lexical/literal; behavioral: reactive/predictive; explicit)
  share a family cap so intra-family corroboration saturates — this
  replaces the synergy bonus and fixes the double-counting.
- Dismissal becomes ordinary negative evidence (a channel whose logit is
  negative), not a post-hoc subtraction.
- The confidence gate becomes `P(top) < θ` with θ a real probability
  (initially matched to today's suppression rate on the bench).
- Multiplicative boosts (freshness, language/implementation intent) become
  additive log-odds nudges; propagation boosts stay as-is until Phase 4
  replaces them.

**Work.** Rewrite `merge.py`; add a small `calibration.py` holding the
per-channel `(a, b, w)` tables; thread the new scale through `boosts.py`,
`explain.py`, and `output.py` (reasons should now show `P` and per-channel
logit contributions — this makes `ken_explain_rank` *more* interpretable,
not less). Old fusion kept behind `KEN_RANKER_FUSION=legacy` for one release.

**Acceptance.** nDCG@8 / recall@8 on Phase 0 bench ≥ baseline; suppression
(empty-block) rate within ±10% of baseline; `ken_explain_rank` output
reviewed by hand on the dogfood cases.

**Risks.** Largest-blast-radius phase; every downstream constant references
the old scale. Mitigated by the legacy flag and by fitting initial
calibration to reproduce current behavior before improving it.

---

## Phase 2 — Adaptive similarity thresholds + embedder upgrade path

**Problem.** Absolute cosine cutoffs (0.40 / 0.42 / 0.45 / 0.48) assume a
stable similarity distribution. A Spanish prompt against English-named code
shifts the whole distribution down and can empty the semantic channels —
the hand-maintained `_TOKEN_ALIASES` Spanish→English table is a patch over
this. `all-MiniLM-L6-v2` is neither multilingual nor code-tuned, and file
embeddings are built from filename + top symbol names only.

**Work.**

- **Per-query adaptive thresholds** (independent of embedder): compute the
  query's similarity distribution over the swept corpus and keep candidates
  with `sim ≥ max(abs_floor, μ_q + k·σ_q)` or `sim ≥ 0.85 · sim_max(q)`.
  The absolute floor drops to a safety net (~0.30). Calibration from
  Phase 1 then maps *relative* similarity to `P_c`, which is exactly what
  a sigmoid over `(sim − μ_q)/σ_q` gives.
- **Embedder option**: support a second ONNX model behind `KEN_EMBED_MODEL`
  presets — one multilingual (e.g. a small bge-m3-class model) and/or one
  code-tuned — with per-model dim handling and a re-embed migration path
  (bump an `embedder_id` column; re-embed lazily like install already
  does). Benchmark both against MiniLM on the Phase 0 set before making
  any new default.
- **Richer file embedding text**: include module docstring first line and
  top-level constant/route/CLI names in the file's embedding text (the
  indexer already extracts these), so file vectors reflect purpose, not
  just naming.

**Acceptance.** Spanish-prompt bench slice (add ~20 Spanish-language cases
to the dogfood set) improves materially; English slice does not regress;
`_TOKEN_ALIASES` demoted to a fallback (deleted only when the multilingual
default lands).

---

## Phase 3 — Kill popularity bias: lift/PMI in predictive and co-occurrence

**Problem.** `predictive_scores` accumulates evidence across similar
sessions with no normalization by a file's base rate — a `cli.py` touched
in every session gains predictive score for *any* prompt. `apply_cooc`
counts raw co-occurring sessions, so ubiquitous files co-occur with
everything. Combined with the exposure feedback loop, behavioral memory
degenerates toward "recommend what's popular".

**Design.** Replace raw accumulation with **lift**:

```
lift(f) = P(f useful | similar sessions) / P(f useful | all sessions)
```

- Predictive contribution per file becomes
  `sim² · decay · raw · pattern_mult · min(lift_cap, lift(f))`, with
  `lift < 1` actively discounting universal files. Denominator from a
  cheap maintained aggregate (per-file session-usefulness counts +
  total sessions — one small table or view over `cr_session_scores`).
- Co-occurrence boost switches from raw session count to the same lift
  (or Jaccard between "sessions where anchor useful" and "sessions where
  candidate useful"), keeping the existing saturation shape.
- Laplace smoothing (+1/+k) so young projects with few sessions don't
  produce wild ratios; below a minimum session count, lift ≈ 1 (neutral,
  current behavior).

**Acceptance.** On the mined bench, precision@8 improves for prompts whose
gold files are *not* the project's most-touched files; hub files (`cli.py`,
`db.py`) stop appearing in ranks where no channel other than
predictive/cooc supports them (checkable via `ken_explain_rank` reasons).

---

## Phase 4 — Personalized PageRank over a unified evidence graph

**Problem.** Import-affinity (with its `8/degree` hub damping),
test-affinity, and cooc are three hand-built 1-hop propagations with ~15
constants between them. They are the first Taylor term of the same
underlying idea; and git co-change (`cochange.py`) — already indexed — is
not used by the ranker at all.

**Design.**

- Build a per-project weighted graph over files with typed edges:
  imports (from `ci_imports`), test↔source pairs (current name heuristics),
  session co-occurrence (lift-weighted, from Phase 3), and git co-change
  (from `cochange.py`'s data, confidence-weighted).
- **Personalized PageRank / random walk with restart** seeded on the
  pre-boost anchors (explicit + reactive + top fuzzy), restart α ≈ 0.5,
  ≤3 power iterations (the graph is small; a few ms at 10K files, and the
  adjacency structure can be cached per index generation and invalidated
  on reindex).
- PPR scores enter the fusion as one more calibrated channel ("structural
  affinity"), replacing `apply_import_affinity`, `apply_test_affinity`,
  and the propagation half of `apply_cooc`. Degree normalization inside
  the transition matrix subsumes the hub-damping hack; α subsumes the
  per-boost propagation/cap constants.
- **Cold start bonus**: the *unpersonalized* PageRank of the same graph is
  a static "load-bearing file" prior (Aider's repo-map insight), used as a
  weak channel when behavioral history is empty (first sessions in a
  project).

**Acceptance.** Bench ≥ Phase 3 results; the three retired boosts deleted
(not flagged off — deleted) once parity is shown; `ken_architecture`'s
hub detection can share the same PageRank computation.

**Risks.** Tuning edge-type weights is a new small constant surface — keep
it to one weight per edge type, fit in Phase 5 like everything else.

---

## Phase 5 — Learned weights from implicit feedback (the payoff phase)

**Problem.** Even after Phases 1–4, per-channel weights `w_c`, calibration
`(a_c, b_c)`, and graph edge weights are hand-set. Meanwhile every real
session streams in implicit relevance labels (Phase 0) and exposure records.

**Design.**

- Feature vector per (prompt, file): the per-channel logits from Phase 1
  fusion (reactive, predictive, fuzzy, doc-intent, lexical, literal,
  explicit, PPR, freshness, dismissal). Model: **logistic regression** —
  interpretable, trivially local, and the fusion is already linear in
  logits, so "training" is exactly fitting the fusion weights.
- **Exposure de-biasing**: weight training examples by inverse propensity
  using `cr_exposures` — a file the agent used *without* it being shown in
  the block is strong positive evidence; a shown-and-ignored file is
  informative negative evidence; shown-and-used is discounted.
- Two-tier weights: a **global prior** shipped with ken (fit on maintainer
  dogfood + opt-in donated benches), and a **per-project delta** updated
  locally (small ridge-regularized update toward the prior, recomputed at
  session end alongside the snapshot — never inline in `rank()`).
- Hard floors so learning can't zero-out explicit mentions or invert the
  dismissal sign — safety rails around the behaviors users directly
  control.

**Acceptance.** Learned weights beat hand-set weights on held-out mined
sessions (temporal split: train on past, test on recent) by a margin on
nDCG@8; per-project adaptation shown to help on ≥2 real projects; a
`ken rank --weights` inspection surface exists so the fitted weights are
auditable, not a black box.

---

## Phase 6 — Output selection: diversity + token-budget optimization

**Problem.** Final selection is top-k by score with a char-truncating
renderer. The top 8 can be redundant (file + its test + its neighbor), and
a high-score huge file crowds out several cheap informative ones.

**Work.**

- **MMR selection** for the file list: greedily pick
  `argmax λ·score − (1−λ)·max_sim_to_selected` using the already-computed
  file embeddings; λ ≈ 0.8. Cheap (k×k cosines over ≤30 candidates).
- **Budget-aware selection**: estimate tokens per entry (path + reason +
  any snippet the renderer adds) and select by score-per-token under the
  block budget (greedy knapsack), instead of top-k then truncate.
- Applies purely in `output.py` / selection layer; scores and explain
  output unchanged.

**Acceptance.** Same-budget blocks contain measurably more distinct gold
files on the bench (recall@budget metric, new in Phase 0's harness).

---

## Phase 7 — Lexical/literal mechanics cleanup (opportunistic, any time)

Not math-critical but removes brittleness and IO cost; can interleave with
any phase after Phase 1:

- **Literal channel off the filesystem**: today it reads up to 256KB per
  candidate file on *every* rank. Replace with an FTS5 (trigram) index in
  the existing SQLite DB, maintained by the indexer/watcher. Same signal,
  ~zero rank-time IO, and enables real IDF weighting for rare-token hits.
- **Lexical channel gets IDF**: replace flat overlap counts with BM25F over
  fields (path tokens, symbol names, docstrings). Subsumes most of the
  hand-listed stopwords; `_project_stopwords` falls out naturally as
  high-DF terms.
- `ken_grep`'s existing BM25 machinery is the natural code to share here.

---

## Sequencing and dependencies

```
Phase 0 (eval + exposure logging)      ── prerequisite for all
   ├── Phase 1 (log-odds fusion)       ── prerequisite for 2's calibration,
   │      │                               4's channel form, 5's features
   │      ├── Phase 2 (adaptive sims, embedder)
   │      ├── Phase 3 (lift/PMI)       ── feeds edge weights of 4
   │      │      └── Phase 4 (PPR channel)
   │      └────────────┴── Phase 5 (learned weights; needs months of
   │                          Phase 0 exposure data — start 0 early)
   ├── Phase 6 (MMR + budget)          ── independent of 2–5
   └── Phase 7 (FTS5/BM25F)            ── independent, any time after 1
```

Suggested order of execution: **0 → 1 → 3 → 4 → 2 → 7 → 6 → 5**, with 5
landing whenever enough exposure data has accumulated. Phases 0+1 are the
foundation; 3+4 are the biggest quality wins for accumulated-history users;
2 is the biggest win for non-English prompts; 5 is the compounding payoff.

## Portability

Everything in this plan runs local-first with ken's existing footprint.
References to Elastic/Qdrant/Cody-style stacks above are *evidence that the
techniques work* (their published benchmarks), not dependencies. The
portable mapping:

- BM25 / lexical index → **SQLite FTS5**, already compiled into stdlib
  `sqlite3`; lives in the same `.ken/ken.db`.
- RRF / log-odds fusion → pure math, plain numpy.
- Vector search → current brute-force numpy sweep (fine to ~100K vectors);
  if ANN is ever needed, `sqlite-vec` is a single-file SQLite extension —
  but see the non-goals below.
- Personalized PageRank → sparse power iteration in numpy; no networkx.
- Logistic regression (Phase 5) → pure numpy; no sklearn.
- Multilingual embedder (Phase 2) → `multilingual-e5-small`: ~120MB ONNX,
  **384-dim** (matches `EMBEDDING_DIM`), supported by fastembed — same
  library ken already uses.
- Cross-encoder reranker (excluded below) would also be portable if ever
  reconsidered (fastembed ships ~70MB ONNX rerankers); it is excluded for
  latency, not portability.

## What we deliberately do NOT do

- **No cross-encoder reranker for now.** A local ONNX cross-encoder over
  the top-30 would sharpen the top-8, but it adds a second model download,
  ~50–200ms per prompt, and memory. Revisit only if Phase 5 plateaus.
- **No ANN index (sqlite-vec/faiss).** Brute-force numpy over ≤100K
  vectors remains milliseconds; complexity not yet paid for.
- **No LLM-in-the-loop ranking.** The whole point is a synchronous,
  deterministic, local pre-pass.

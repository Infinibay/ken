# ken — Stochastic (non-LLM) tooling roadmap

> Goal: give ken tools so an agent can ask "how does X work?" and get a **trustworthy answer
> computed by stochastic/algorithmic means** — no LLM inference inside the tool. The division of
> labor: **tools do graph math, association statistics, and structural extraction with citations;
> the LLM narrates over cited, coverage-flagged evidence.**

Source: brainstorm workflow `ken-stochastic-ideas` (8 lenses → 86 ideas → adversarial critique →
synthesis). Recurring failure mode the critique punishes: laundering noisy approximations
(perplexity-as-bug, random-walk-as-dataflow, SZZ attribution, dead-code probabilities, Markov
"playbooks", Mahalanobis anomalies) into authoritative-looking output an LLM will over-trust.
Winners are **precision-first, evidence-cited, and honest about coverage**.

Dogfooding note that motivated this: `ken_module_graph` returns a sparse, often unidirectional
import graph, and `ci_references` exists in the schema but is **never populated** — ken cannot
answer "what calls what / how does data flow" today.

---

## Top tools (ranked)

### 1. `ken_cochange` — git commit-history co-change association mining  · effort M · **flagship**
- **Q:** "When I touch X, what else historically has to change with it — including hidden couplings
  imports can't see (schema↔migration, code↔config, parallel implementations)?"
- **How:** ingest `git log --name-only --follow` into new `cr_commits`/`cr_commit_files` (incremental
  from last-seen SHA in `meta`). Each commit = market-basket transaction. Mine pairwise co-change with
  support, `confidence(A→B)=co/count(A)`, `lift=P(A,B)/(P(A)P(B))` to discount churny files.
  Exponential recency decay (half-life ~90d), drop commits touching >~30 files (reformats/vendor/merge),
  require `min-support≥3` and `lift>1`. **Subtract the `ci_imports` edge set** so the headline is the
  hidden, non-structural coupling. Optional overlay: session co-edits from `cr_interactions`.
- **Data/algo:** NEW `cr_commits(sha, ts, author, msg)` + `cr_commit_files(commit_id, file_id)`;
  consumes `ci_files`, `ci_imports`. FP-growth/pairwise association rules + PMI/lift + time decay.
- **Sig:** `ken_cochange(path, min_confidence=0.4, min_support=3, limit=15) -> [{path, support,
  confidence, lift, recency_weight, has_import_edge:bool, last_co_changed}]` — empty below threshold,
  never guesses.

### 2. `ken_callgraph` — tree-sitter call-site extraction into `ci_references` · effort L
- **Q:** "Who calls function X, and what does X call?" (ken's single biggest gap)
- **How:** new extraction pass over the EXISTING tree-sitter ASTs collecting real `call_expression`/
  `method_invocation` nodes (not token scans — kills string/comment/attribute false positives).
  Resolve callee to a `ci_symbols.id` only in precision tiers: **T1** = same file OR name unique in
  repo; **T2** = callee's file is the single resolved `ci_imports` target; **T3** = ambiguous → do NOT
  argmax, record candidate set unresolved. Persist only T1/T2 into `ci_references` with
  `confidence`+`resolution_reason`. Lead with same-file edges; gate T3 behind verbose.
- **Sig:** `ken_callgraph(qualname|path, direction=callers|callees|both, min_confidence='T2', depth=1)
  -> {edges:[{from_qualname, to_qualname, file, line, confidence_tier, reason}], unresolved_callsites}`.
- Foundational primitive other tools consume.

### 3. `ken_architecture` — SCC cycles + topo layers + communities + PageRank (coverage-honest) · effort M
- **Q:** "What are the real subsystems, layers, dependency cycles, and load-bearing hubs — beyond
  directory counting?"
- **How:** on the resolved `ci_imports` digraph: (1) **Tarjan SCC** to report import cycles (the one
  high-precision output — a reported cycle uses only real edges); (2) topological levelization of the
  condensation = approximate layer index; (3) **Louvain** communities on the undirected projection,
  optionally densified with embedding-kNN edges; (4) weighted **PageRank** for hubs + reverse-PageRank
  for foundations. Label clusters via `ken_profile` log-odds terms. **Every result carries an
  edge-coverage header** ("resolves 140/210 imports"); cycles headlined high-trust, layers/communities
  marked approximate.
- **Sig:** `ken_architecture(depth, limit) -> {edge_coverage:{resolved,total}, cycles, layers, clusters,
  hubs, sinks}`.

### 4. `ken_intent_history` — prompt→files retrieval via embedded `user_prompt` kNN · effort S
- **Q:** "When someone asks 'fix the session resume bug', which files do that KIND of request touch?"
- **How:** user prompts are already embedded[384] in `cr_contexts`, anchored to interactions via
  `context_id`. Embed the query, take N nearest historical prompts by cosine, aggregate the anchored
  `cr_interactions` into a file table weighted by `cosine(prompt) × interaction weight`, deduped per
  session. Return files + the matched prompt texts + similarities (so the agent sees WHY). Relevance-by-
  outcome, structurally distinct from content-embedding search. No new data.
- **Sig:** `ken_intent_history(query, k_prompts=12, limit=15) -> [{path, behavioral_score, times_touched,
  matched_prompts:[{text, similarity}]}]`.

### 5. `ken_wiring` — routes / CLI / env-var / config-key → handler extractor · effort M
- **Q:** "How is X wired up — which route, CLI subcommand, env var, or config key triggers it, and what
  handler runs?"
- **How:** AST extraction of decorator/registration nodes (`@app.route`, `@router.get`, `add_subparser`,
  `click.command`, hook registration) + token-class regex only for literal payloads (`/users/{id}`,
  `--flag`, `UPPER_SNAKE`). Bind each to the enclosing symbol by binary-searching `ci_symbols` line
  ranges. Confidence tiers (decorator = high, bare UPPER_SNAKE = low). Persist `ci_wiring`. This is the
  real entrypoint table that should SEED reachability/flow queries.
- **Sig:** `ken_wiring(query|trigger_kind=route|cli|env|config|hook) -> [{trigger, handler_qualname, file,
  line, confidence, framework}]`.

### 6. `ken_profile` — weighted log-odds distinctive-term briefs (file & dir) · effort S
- **Q:** "What is this file/package for, and what distinguishes it from its siblings?"
- **How:** treat each file/dir as a document of tokenized `ci_symbols` names/qualnames + first-line
  docstrings + `ci_intent_sources`. Score terms with **Monroe et al. weighted log-odds-ratio under an
  informative Dirichlet prior** (more trustworthy than TF-IDF/NMF on small corpora). Return distinguishing
  vocabulary + representative files + nearest-sibling cosine. Report evidence strength. Absorbs file_gist,
  dir_profile, package-purpose, topic-model ideas; doubles as `ken_architecture`'s cluster labeler.
- **Sig:** `ken_profile(path, granularity='file'|'dir', top_terms=12) -> {label, distinguishing_terms,
  representative_files, nearest_siblings, evidence_strength}`.

### 7. `ken_clones` — MinHash/LSH near-duplicate & copy-paste detector · effort M
- **Q:** "Where else is this implemented? Is this function copy-pasted, and how do copies differ?"
- **How:** per symbol, read source live, normalize (strip comments/whitespace), k-shingle. 128-permutation
  **MinHash** signature; **LSH banding** for near-linear candidates; confirm with estimated Jaccard.
  Persist `ci_minhash` keyed by `content_hash` (one-time O(N), incremental). Anti-boilerplate floor
  (≥15 distinct shingles), report only Jaccard≥0.75 over contiguous lines, rank by similarity×symbol_size.
- **Sig:** `ken_clones(path, qualname=None, min_similarity=0.75, min_shingles=15, limit=10) -> [{qualname,
  file, similarity, overlap_line_span}]`.

### 8. `ken_grep` — BM25 + literal/exact FTS search · effort S · **boring win, ship early**
- **Q:** "Which files contain this literal route / env-var / constant / regex, ranked by relevance?"
- **How:** SQLite **FTS5** with a custom tokenizer that PRESERVES snake/kebab/dotted tokens (so
  `MY_ENV_VAR`, `os.path` are findable), keyed by `content_hash`, maintained by the indexer. Literal/exact-
  phrase as primary contract; **BM25** (k1≈1.2, b≈0.75) ranked fallback. Always re-scan changed files from
  `git status` so it never lies vs disk. Exposes the ranker's internal `literal_content_scores` as a tool;
  underpins config-flow, canonical-usage, dead-name checks, wiring's token half.
- **Sig:** `ken_grep(query, mode='literal'|'bm25', language=None, limit=20) -> [{path, score, snippets}]`.

### 9. `ken_type_hierarchy` — inheritance & override graph · effort M
- **Q:** "What subclasses X / implements Y? Which subclasses override method m? Where's the base impl?"
- **How:** extend each parser's class handler to capture superclass/interface clauses (Python arglist,
  TS/Java `extends`+`implements`, Rust `impl…for…`, Go embedded structs). Store the raw parent name string
  (lossless); resolve to `ci_symbols.id` only when unambiguous via resolved imports, else external base.
  Persist `ci_inheritance`. Answer via transitive closure; detect overrides by name-set intersection across
  a class and its ancestors (best-effort, ignores signatures). Go interface satisfaction via method-set
  containment offered as explicitly-approximate.
- **Sig:** `ken_type_hierarchy(qualname, direction=sub|super, with_overrides=true) -> {ancestors|
  descendants, overrides}`.

### 10. `ken_blast_radius` — file-level reverse reachability + co-change + tests · effort S
- **Q:** "If I change this file, what else is likely to break or need touching — and on what evidence?"
- **How:** reverse-BFS over `ci_imports` (transitive importers + hop distance) ∪ `ken_find_tests`
  (test-of) ∪ `ken_cochange` (historically co-changed Nx). Report each dependent with **per-channel
  evidence** ("imports", "co-changed 8x", "test-of") and hop distance — NOT a fused black-box scalar.
  Explicit: traces resolved imports only ("N unresolved — LOWER bound"). Lead with reachable entrypoints.
  Symbol-level edges later, once `ken_callgraph` proves T1/T2 precision.
- **Sig:** `ken_blast_radius(path, max_hops=4) -> {direct_importers, transitive, reachable_entrypoints,
  coverage_note}`.

---

## Sketch — `ken_interpreter` (escape hatch, develop later)

> Idea (rough, to be detailed): a tool you pass **Python code** to. Inside its sandboxed env, classes and
> methods are **pre-defined and available** that expose **ken's core** — explore code, search the index,
> walk the graph, read symbols/embeddings — and return the result. For advanced, manual, composed queries
> that no single purpose-built tool covers. The agent writes a short script against a curated ken API and
> gets structured output back.

Open questions to resolve when we design it:
- The exposed API surface (a `Ken` facade: `.search()`, `.symbols()`, `.callers()`, `.graph()`,
  `.embed()`, `.cochange()`, `.read_lines()` …) — thin wrappers over the same core the other tools use.
- Sandboxing / safety: no filesystem write, no network, time/memory budget, read-only DB handle.
- Return contract: capture a designated `result` variable (JSON-serializable) + stdout.
- Whether it runs in the daemon process (warm index, shared caches) vs a subprocess.

It composes all the tools above: each ranked tool is effectively a "blessed recipe" the interpreter could
also express manually.

---

## Honorable mentions

- **`ken_test_contract`** — tests-as-spec: list test-function names verbatim (human-written behavior labels)
  as a checklist via `ken_find_tests`. Asserted-symbol attribution secondary/tree-sitter; drop soft
  "coverage_density".
- **`ken_invariants`** — implicit-contract miner: tree-sitter extract `assert`/`raise`/early-return/None-check
  guards per symbol, return VERBATIM with line cites as "guards found here". Drop PrefixSpan; let the LLM
  infer the contract.
- **`ken_config_flow`** — index env/config keys (`os.environ`/`process.env` + scraped toml/json/yaml), map
  exact read/write sites with enclosing symbol (on `ken_grep`). Drop forward-taint "downstream_uses".
- **`ken_canonical_usage`** — most-common usage finder: scope candidates to files importing the symbol's
  module (via `ci_imports`), rank by occurrence + reader frequency, MinHash-dedupe, top-3 snippets labeled
  "most common" (not "canonical").
- **`ken_symbol_interactions`** (forward capture, indexer/daemon change not a query tool) — on Edit, locate
  `old_string`, binary-search `ci_symbols` for the enclosing symbol, write the never-populated
  `target_kind='symbol'` rows. Enables symbol hotspots/co-edit (Beta-Binomial shrinkage). No historical
  backfill (no line ranges stored).
- **`ken_hotspots`** — churn×size: recency-weighted churn × (symbol_count + summed line-span) into fixed
  quantile quadrants. Absorbs fix-commit density as a "defect" axis (replaces cut SZZ tool).
- **`ken_lineage`** — rename/move tracer: git-native `--follow -M -C` chains (high-trust); gate MinHash
  split-detection behind a low-confidence flag.
- **`ken_feature_dossier`** (deferred orchestrator) — once `ken_callgraph` + `ken_cochange` validated, a thin
  DETERMINISTIC aggregator stitching cited sub-results (wiring entrypoint + reachability + tests + coupling)
  with per-section confidence/coverage labels. Entrypoint from `ken_wiring`, not PPR magic. Build last.

---

## Cross-cutting infrastructure (each unlocks many tools)

1. **Commit-history ingestion** (`cr_commits` + `cr_commit_files`, incremental via last-SHA in `meta`,
   `--follow` rename tracking, commit-size cap): biggest unlock. Powers co-change, hotspots, defect density,
   evolution, lineage, behavioral blast-radius. Today ken only reads live `git status`.
2. **One tree-sitter structural-extraction pass** reusing existing parsers (py/js/ts/rust/c/go/java/dart):
   harvest call nodes (→ `ci_references`), decorator/registration nodes (→ `ci_wiring`), extends/implements
   (→ `ci_inheritance`), guards (→ invariants). Replaces every fragile raw-token/regex approach.
3. **Identifier-preserving FTS index** (SQLite FTS5, worktree-fresh): exposes `literal_content_scores` as
   `ken_grep`; underpins config-flow, canonical-usage, dead-name, wiring's token half.
4. **Trust-and-coverage convention on EVERY graph/stats tool**: report edge-coverage, use confidence tiers
   (T1/T2/T3; strong/weak), enforce min-support floors, **return EMPTY rather than smoothing noise into
   existence**, surface per-channel evidence instead of fused black-box scalars or fake probabilities.
5. **Distinctive-term contrast** (weighted log-odds + Dirichlet prior) as a shared labeling layer: names
   architecture clusters, profiles dirs/files, labels co-change groups. One statistic reused everywhere.

---

## Recommended build order

1. **`ken_cochange` + commit-history ingestion** — flagship; fills the #1 gap; the commit table is the
   substrate for hotspots/defect-density/evolution/lineage/blast-radius. Ship with commit-size cap, recency
   decay, min-support/lift floors.
2. **`ken_grep`** (FTS5) — one-day boring win, dependency for several later tools.
3. **`ken_callgraph`** + the shared tree-sitter extraction pass — unlocks wiring, type-hierarchy, invariants,
   symbol-level blast-radius.
4. Then the graph/stats layer (`ken_architecture`, `ken_blast_radius`, `ken_profile`, `ken_clones`,
   `ken_intent_history`) and finally the deferred `ken_feature_dossier` + `ken_interpreter`.

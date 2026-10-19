# Final whole-plan review: native Spanish query expansion

Reviewed committed range `1ae4bb97..14da4bcc` on `codex/rust-migration`, against the translation spec, four-task plan, progress ledger and five verbatim review focuses. This is the one fresh review. No application, test, index, HEAD or branch changes were made; no subagents or second reviewer were used. This report is the only retained file written by the review. Focused experiments used temporary directories, existing binaries and intercepted build commands; no native rebuild or full-suite repeat was performed.

## Strengths

- The responsibilities are coherent: `TranslationModel` declares identity, `PreparedTranslation` retains authenticated bytes, `ProtectedQuery` owns one query's substitutions, and `LocalQueryExpansion` owns one serialized native session. Runtime loading materializes owned verified bytes in a private retained directory and loads SentencePiece from serialized bytes. This avoids reopening mutable model/cache paths after authentication (`translation_preparation.rs:69`, `query_expansion.rs:84`, `query_expansion.rs:108`).
- The migration preserves difficult original behavior deliberately: Unicode 15 predicates/casefold, Python boundaries, regex priority and greediness, sequential placeholder collisions, whitespace between every placeholder character, and damaged placeholders. Independent original-generated fixtures and the whole-scalar digest are substantially stronger evidence than examples derived from the port.
- Successful and failing calls share the same product operation. `ExpansionAttempt` retains actual encoded inputs before inference; traces are owned and there is no shared last-result state. English stays lazy, construction failures remain retryable, and model calls remain serialized (`query_expansion.rs:177`, `query_expansion.rs:250`, `query_expansion.rs:277`).
- The real per-platform oracles include 511/512/513 and 1023/1024/1025 source-piece boundaries, raw and restored text, token IDs, hypotheses and failures. The Release override and Accelerate/OpenBLAS distinction address observed numerical differences rather than assuming cross-platform text equality.
- Acceptance composes prior receipts recursively, checks exact case/input identities, binds supplied probes to release bytes, selects the CT2 build directory from Cargo JSON, and uses independent native preparation outside the checkout. The explicit build inputs propagate through the nested validators without mutating the parent environment.

## Issues

### Critical

None found.

### Important

1. **A valid, moderately sized query can panic instead of returning an expansion or `ModelError`.**

   **Location:** `crates/ken-models/src/query_policy.rs:56` (ambiguous underscore alternative constructed at line 30).

   `Regex::find_iter` calls Onig's panicking search API. The underscore alternative can repartition a long underscore run quadratically when a following Unicode word character prevents the required ending boundary. Once Onig reaches its default retry limit, this escapes the public `Result` boundary.

   **Reproduction:** With the recorded immutable release probe and the tiny authenticated preparation fixture, pass a query constructed as `"¿ " + "_" * 5000 + "é"`. The process exits **101**, produces no JSON, and reports `Onig: Regex search error: retry-limit-in-match over` at onig 6.5.3 `src/lib.rs:647`. The exact original Python protection regex returns no matches in approximately 0.09 seconds. Runs with 500 and 2000 underscores return normally; 10000 also panics. The probe's SHA-256 was checked against the committed macOS release receipt before relying on this result.

   **Effect:** Pasting a few kilobytes of degenerate identifier-like text can terminate the probe/calling thread or process instead of following the original translation/error path. This is a functional failure, not merely a performance concern, and it happens before model loading.

   **Fix:** Remove the avoidable ambiguous matching while preserving the original exact match semantics, and use the fallible Onig search interface for remaining runtime errors. Add independent-original regressions for long underscore/Unicode-boundary cases and confirm the normal `expand_attempt` path remains usable afterward. Merely catching the panic or imposing a new input cap would leave a parity gap for an input the original protection policy handles.

2. **OpenBLAS preparation can execute build instructions from archive bytes that were never authenticated.**

   **Location:** `tools/rust_migration/translation_build.py:75`, `:88`, `:92` (the later reopening/copy at `:104` also participates).

   `prepare_openblas` authenticates the caller's archive path, then reopens that mutable path for extraction. It later opens the path again to retain `source.tar.gz`. A replacement between verification and extraction therefore changes the Makefile/source actually passed to `make`. The late receipt verification cannot undo execution of those unverified build instructions; replacing the original archive again before the retained copy can also make the receipt attribute the build to different bytes.

   **Reproduction:** A deterministic temporary-directory experiment started with the real pinned archive, for which `_record` matched the declared 24,404,912-byte/SHA identity. Immediately after that check, the test replaced the path with a different valid tar containing a sentinel Makefile. Actual extraction succeeded and the helper reached its `make` invocation with that replacement Makefile. The experiment intercepted `make` and returned failure, so no replacement build code ran. The observation was `checked: true`, `make_reached_with_unverified_source: true`.

   **Effect:** A concurrent archive replacement or update defeats the promised source authentication at the boundary that executes third-party build instructions. It can build unchecked native code or execute an unchecked Makefile before eventual failure.

   **Fix:** Own one regular, size-bounded archive snapshot, authenticate those bytes, and extract and retain that same snapshot. Do not reopen the caller's archive path after authentication. Add a deterministic replacement regression that proves the extracted/build input remains the authenticated snapshot or fails before any build command.

### Minor

1. **The declared bounded-integer JSON subset rejects lexical negative zero.**

   **Location:** `crates/ken-models/src/translation_json.rs:39`.

   Serde delivers JSON `-0` through `visit_f64`, which currently rejects it. The original normalizer treats `{"x": -0}` as the integer zero and emits `{
     "x": 0
   }` with the normal config newline. A public-probe experiment using an authenticated tiny source and the matching Python-derived declaration exited 1 with `unsupported floating or out-of-range translation JSON number`.

   This does not affect the fixed published model, whose config contains strings/bools/null, so it is Minor. It does make the documented bounded-integer subset narrower than stated. A later change should either preserve lexical integer `-0` separately from unsupported `-0.0`/exponent forms or explicitly document the narrower subset.

2. **The named two-distinct-words neural history does not exercise that condition.**

   **Location:** `tools/rust_migration/translation_reference.py:18`.

   The case is `busca la`, but `la` is not in the original lexicon, so this history is a passthrough. The separate lexicon and accent-alias cases cover the real two-distinct-word behavior, making this a coverage-label issue rather than a product defect. Rename the history or, in a deliberate future oracle update, add a correctly named case such as `busca clase`; do not silently reinterpret the frozen output.

## All five review focuses

| Review focus | Coverage and result |
| --- | --- |
| 1. Unicode casefold/boundaries and regex greediness around dollar signs, combining marks, digits and empty backticks must preserve the decision and exact matches. | Read the original pattern, explicit Unicode classes and native matcher; reviewed original fixture generation, whole-scalar digest, lexical/restoration tests and dollar/mark/digit/backtick histories. Important issue 1 exposes a longer boundary case absent from the fixture corpus. |
| 2. Placeholder collisions, multi-digit indices, unusual whitespace and model-damaged placeholders must preserve original restoration without leaked cross-call state. | Reviewed sequential restoration, per-call owned vectors, Python-space handling and ASCII-only matching of the actual key alphabet. Covered collisions, indices above 9, damaged keys, literal replacements, returned-trace independence and concurrent query tests. No defect found in restoration or ownership. |
| 3. Corrupt/replaced sources or caches and simultaneous preparation/loading must never load unchecked bytes, publish partial data, deadlock or turn failure into text. | Reviewed opened-file verification, owned snapshots, private staging, directory/file sync, concurrent-winner verification, private native materialization, retained lifetime and mutex/error flow. Model-data ownership is sound in the inspected paths. Important issue 2 applies the same authenticated-byte requirement to the new native build preparator. |
| 4. Degenerate long inputs and platform numeric backends must retain translations and512/1024boundaries; a working short example cannot certify parity. | Reviewed all boundary case construction, original measured lengths, native EOS/options and exact raw/public comparison paths. Both platform records retain the differing original outputs and relevant Release/backend identities. Important issue 1 shows that neural token-boundary coverage does not cover degenerate lexical preprocessing. No numeric tolerance or output whitelist was found. |
| 5. Wrong/stale executables, foreign-platform native libraries, Python-only preparation or missing prerequisite propagation must fail acceptance, including nested prior gates. | Reviewed fresh-release hash binding, Cargo-selected build evidence, platform/library policies, sentinel/exec process checks, independent preparation, typed prerequisite propagation and recursive receipt validation. Rechecked both committed receipts successfully. Important issue 2 is the remaining source-provenance gap; no additional stale-executable or prerequisite-propagation defect found. |

## Evidence and ledger assessment

The review covered implementation and test owners, oracle/fixture generators, probe/comparator/build/validation tooling, dependency/profile changes, CI propagation, and meaningful passes over the large frozen fixture/evidence package. Generated rows were assessed through their generators, digest contracts, tests and boundary histories rather than claiming a manual proof of every JSON row.

Re-evaluating `translation_receipt_errors` against the committed matrix and exact case registry returned **no errors on either platform**. Each receipt contains 26 gates and 24 fingerprints. Summing the committed Rust test summaries gives **132 passed, 0 failed, 0 ignored** on each platform. The Python logs report **15670 passed, 10 xfailed** on each platform. These confirm what the existing receipts say; they do not make the new failing inputs pass or certify a future corrected candidate. The immutable executable used in the focused experiments matches the committed macOS release SHA.

The ledger's decisions to retain actual failed-call input, distinguish Rust errors from explicitly mapped Python errors, pin the observed native numeric backend/build mode, fingerprint embedded data, and propagate typed native prerequisites are justified. Precompiling test binaries before the unchanged 600-second execution gate is a transparent preparation step; the retained cold-run failure and disk-pressure attempt are not represented as passes. The recorded socket-permission rerun and private-cache cleanup do not imply a product workaround. Final review after task-done remains a separate acceptance gate as documented, so the pre-review matrix must not be used to close this profile with these Important defects outstanding.

## Recommendations

- Use the authorized single Critical/Important TDD correction pass for issues 1 and 2. Keep the original policy and byte-ownership responsibilities authoritative; no new fallback text or acceptance relaxation is needed.
- Preserve the failing lexical input and archive-replacement interleaving as regression evidence. Keep the existing large corpus, numerical histories and typed error checks intact.
- New native/validator source fingerprints will invalidate the current acceptance binding. Obtain current-candidate validation evidence required by the plan after the fixes; retain these existing receipts as evidence for the reviewed revision.
- Defer the two Minor findings under the agreed workflow. No second review is requested.

## Declined to judge — executor ruling required for each item

1. **Full retrieval/CLI/MCP wiring and the remainder of M2/M3–M8:** this cut exposes native query expansion; whole-application migration and routing remain explicitly open. No approval of those future behaviors is implied.
2. **Public model acquisition, automatic selection/download, installation/promotion, push/merge and deletion of original Python code:** these actions are explicitly outside this profile and were not performed. The explicit local preparation/runtime paths were judged here.
3. **Windows, x86_64, other native backends, and cross-platform equality of already different original translations:** only the registered ARM macOS/Linux profiles are in scope. Wrong-platform rejection and preservation of each platform's original behavior were judged.
4. **Redesigning original language detection, improving translation quality, or repairing original literal-placeholder collisions and damaged-placeholder output:** this migration promises compatibility with those original decisions. Their preservation was judged; changing their product semantics requires separate work.
5. **General Python JSON compatibility beyond the documented representation:** floats, duplicate keys, unpaired surrogates, oversized input and deeper nesting are explicitly rejected. Those rejection boundaries were inspected; broader support was not required. Integer `-0` was retained as a Minor finding rather than silently excluded.
6. **New latency, throughput, mutex fairness or memory SLAs:** the profile records measurements and explicitly makes no new SLA/speedup promise. The concrete regex panic was judged as a functional defect despite this exclusion.
7. **Actual remote GitHub Actions execution, hosted-runner availability and deployment outcomes:** the local workflow changes were inspected, but no remote run or deployment was performed or claimed. The local two-platform evidence was judged on its own merits.

## Verdict

**Ready to merge/accept this profile: With fixes.**

The concept ownership, original-independent parity evidence and nested acceptance plumbing are strong, but the valid-input regex panic and unauthenticated OpenBLAS extraction/build window must be corrected before profile closure. No Critical issues were found; there are **2 Important and 2 Minor findings**. Overall M2 and the later migration stages remain open.

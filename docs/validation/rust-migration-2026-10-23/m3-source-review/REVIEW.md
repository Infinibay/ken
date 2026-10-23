# One final whole-plan review

Reviewer: fresh-context `gpt-6-astra`, high reasoning, `/root/m3_sources_final_review`.
Scope: `1ace9d68..c1bb03c5`, read-only. Historical model evidence excluded.
Verdict: **Not ready to accept M3a. Six Important findings require repair.**
Critical: none. Minor: none. No second review requested.

The reviewer verified the exercised macOS probe against its recorded binary hash,
replayed the historical matrix, and compared 80 additional original/native walks.
Strengths: clear filter/traversal ownership, fresh rule caches, meaningful static
symlink, pruning and ordinary-user permission tests.

## Important findings, retained in full scope

1. **Brace patterns change source membership**, `source_filter.rs:83`.
   `.gitignore` `a{b,c}.py`: original excludes the literal name and includes
   `ab.py`/`ac.py`; globset does the reverse. Add original-derived fixtures and
   preserve literal braces.
2. **Unicode wildcards operate on bytes**, `source_filter.rs:65`.
   `a?.py` and `a[!b].py` exclude `aé.py` in the original, while Rust includes it.
   The literal Unicode fixture misses this. Cover character wildcards and negated
   classes through public filter and walker.
3. **Parent matching changes negation/pruning**, `source_filter.rs:174,152`.
   Rules `foo/*` then `!foo/`, tree `foo/deep/main.py`: original includes the file
   for `.`, `foo`, `foo/deep`; Rust prunes it. `**/` preserves root files in the
   original, while Rust drops even `.gitignore`. Explicit whole-path directory
   match/precedence must replace `matched_path_or_any_parents`; preserve barriers
   and actual ancestor pruning.
4. **Descending ranges silently discarded**, `source_filter.rs:88`.
   `a[z-a].py` raises `re.error: bad character range z-a` in pinned pathspec1.1.1;
   Rust discovers files without error. The ruling that all invalid ranges are
   discarded is wrong: the prior fixture proves only unclosed classes. Correct
   ruling/docs and separately test tolerated and rejected syntax.
5. **Unavailable scope below a file errors**, `source_walk.rs:40`,
   `source_filter.rs:122`. `file.py/child` and `file.py/child/grandchild` yield no
   entries in the original, but Rust tries `file.py/.gitignore` and reports
   NotADirectory. Check unavailable scopes before impossible ancestor rule reads,
   preserving genuine access failures.
6. **Queued directory escapes between iterator calls**, `source_walk.rs:165`.
   Yield/queue an empty in-root `queued/`; replace it with a symlink to an empty
   external directory; collect the iterator. Rust enumerates it and returns an
   empty remainder without error. Revalidate before opening and use a confined
   handle if replacement during open is covered. Add deterministic public API
   regression. Reviewer compiled only a tiny temporary consumer against the
   recorded release rlib; checkout untouched.

Recommendation: one TDD repair pass and extended native acceptance evidence.
Declined to judge: M2/neural correctness, parsers, indexing, installed CLI.
The architecture is suitable, but these findings prevent acceptance of the
reviewed revision. Closure is recorded separately with changed source identities.

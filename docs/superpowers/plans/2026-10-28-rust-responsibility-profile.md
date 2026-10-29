# Native indexed responsibility profiles

Goal: finish ken_read(include=["profile"]) and the library's file/package
responsibility profile on Linux x86_64 without models or index writes.

IndexNavigation supplies a read-only snapshot; a focused profile module owns
identifier tokenization, corpus counts, weighted log-odds and evidence strength.
Callers request nav.profile(path, granularity, top_terms), or the existing public
read include. Reuse ordered documents and shared CLI/MCP boundary. Preserve the
original path normalization (including root-directory and hidden-name quirks),
stop words, prior1000, positive z selection, two-decimal rounding and minimum
one requested term. Exact-score ties are unspecified Python-set order; native
uses lexical tie order. Capture a fresh corpus and compare original data/text,
plus local tied-term determinism. One observed directory has client/explanation
with identical target19/rest0 counts and thus exactly equal scores; the test
proves these counts and permits only that pair's ordering to differ. The original
fixture stays immutable, with no recapture or input retuning. All other ordering,
scores and public data/text compare exactly.

One implementation batch then combined targeted validation of profile/library,
actual CLI/MCP and existing navigation/search boundaries. One final read-only
review; focused reruns for concrete findings only. Preserve originals/workspace
locally, commit and push to the existing authorized branch. No broad CPU/CI or
numeric acceptance changes.

- [x] Observe original16library/5public cases once and preserve raw journals.
- [x] Implement vocabulary/scoring and public profile include in one batch.
- [x] Combined targeted validation and focused tie comparison correction.
- [x] Fresh read-only review: no additional Critical/Important or Minor findings.
- [x] Update usage/handoff and future qualification counts; preserve local evidence.

Validation:9native roots across search library/navigation/text/profile and actual
CLI/MCP, strict Clippy, formatter and diff checks. No production correction was
needed; the single exact-score tie comparison was scoped and proven without
changing source data, scores, original fixture or other ordering assertions.

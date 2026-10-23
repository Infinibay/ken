# Review repair decisions

All six Important findings are accepted. No Critical or Minor finding was raised.
No finding is deferred. This is the plan's one repair pass, with no rereview.

- **Findings1–4, one shared root cause:** `ignore`/globset implements a different
  pattern language and ancestry selection from frozen pathspec1.1.1. Adapting
  isolated strings would leave bytewise Unicode and precedence incorrect.
  Replace the engine with `SourcePatterns`, a focused character-based translation
  and exact-file/directory-priority decision. `SourceFilter` continues to own
  scoped composition and independent barriers. Reuse already locked regex1.13.1;
  remove the three newly unused packages without upgrading any other dependency.
  Cost if wrong: membership changes; independent captures exercise root Git,
  root Ken and nested Git, literal braces, Unicode/emoji wildcards/classes,
  directory priorities and malformed syntax.
- **Supersedes Task1 invalid-range ruling:** only unterminated class notation
  is a no-op in the observed original. Descending ranges fail during regex
  compilation; dangling escapes and bare `!` are errors. Preserve those errors,
  never silently discover files after discarding such a rule.
- **Licensing:** `source_patterns.rs` adapts pathspec's normalization,
  translation and priority algorithm under MPL2.0, with attribution, a source
  notice and the full license in `crates/ken-core/licenses`. The crate declares
  `MIT AND MPL-2.0`; the rest of Ken retains its own license. This is a native
  Rust implementation, with no Python runtime or shell Git invocation.
- **Finding5:** check target metadata before loading ancestor Git rules. A scope
  below a file is unavailable; access errors remain explicit. The original root
  rule initialization remains in place.
- **Finding6:** canonical confinement must be checked when pending directories
  are opened. After revalidation, `source_directory` enumerates through a held
  root descriptor and component-wise `openat(O_DIRECTORY|O_NOFOLLOW)`, then
  `fdopendir/readdir`. This closes the replacement window for enumeration itself,
  including ancestor replacements; internal aliases retain logical identities.
  A changed internal target produces InvalidData rather than reusing stale
  ancestry. Names are copied as native bytes; no `/dev/fd` path becomes identity.
  The initial scoped ancestry is ordered root→target to match queued ancestry.

Historical acceptance remains tied to its source snapshot. The earlier automatic
matrix did not cover the six reviewed failures; it is not claimed as evidence
for the repaired code. Current native captures include both the historical corpus
and the new review corpus. Model inference and unchanged Python suites are reused.

Build corrections within the repair pass: an initial compile exposed the leftover
`SourcePatterns::empty` call; the first green attempt exposed reversed initial
ancestry. A macOS experiment showed `/dev/fd/N` cannot enumerate a directory, so
production uses descriptor-native `fdopendir` instead. An initial offline lockfile
regeneration selected three unrelated newer packages; their versions were restored
before acceptance. The RED failures and initial lock log are retained; transient compile/ancestry failures are described here, not presented as passing gates.

An additional focused probe during this same repair pass reproduced `a[a--b].py`: Python rejects its descending a-to-hyphen range while Rust regex accepts set subtraction. A new RED case drove explicit class-range parsing, including escaped literal hyphens. Final platform gates and captures were rerun only because production sources changed; original valid-tree captures and all model histories were reused. Four distinct malformed errors and three no-op class forms are retained.

The receipt verifier rejected Linux's first source identity because the tar transfer had introduced AppleDouble `._*.rs` metadata, which source_identity correctly enumerated as extra files. Only those controller-created files in the copied ken-core tree were removed. The unchanged native binary was recaptured after cleanup; no model inference, Rust test or compiler rerun was warranted. The mismatching first captures remained disposable workspace diagnostics until closure.

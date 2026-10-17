# UTF-8 admission and legacy-index repair

The failed V219 Zig worker indexed `lib/std` and subsequently aborted while
preparing contextual search. Its first invalid byte was 0x95. The source was a
compressed flate fuzz fixture, `compress/flate/testdata/fuzz/deflate-stream.input`,
not malformed Zig implementation text. Other compressed fixtures in that tree
also contained invalid UTF-8. Some contained no NUL byte, so the existing NUL
filter did not reject them.

The two components disagreed about the source contract. `extract_passages`
replacement-decoded arbitrary bytes into apparently readable text, authenticated
those passages to the original byte hash and stored them. `SourceCatalog` then
strictly decoded the authenticated physical file to recover lines. That second
operation raised UnicodeDecodeError and aborted preparation for the entire repo.
Replacing errors again in the catalog would have hidden this disagreement and
presented a fabricated decoding as physical source.

Commit 1b07976d makes passage admission require valid UTF-8, in addition to the
existing NUL exclusion. Invalid bytes produce no retrieval passages. Valid UTF-8
with an unfamiliar extension remains eligible, including Unicode and CRLF. This
is an explicit UTF-8 source contract, not general-purpose encoding detection:
legacy encodings would need a coherent decoder/coordinate/presentation policy.
The structural file record can remain in `ci_files`; it does not authorize a
retrieval passage for unreadable source.

An extractor version bump alone was insufficient. Incremental indexing checks
that version, but best-search projection reuse previously checked only the
retrieval profile. A matching profile could retain the old binary passages.
The repair therefore has two boundaries:

- Storage rejects obsolete extractor metadata before returning stored passages,
  with IndexVersionError. Public find/find_best return their existing actionable
  preparation response, including the exact lookup path.
- Best-search preparation also checks the extractor before reusing a profile.
  It reconstructs legacy source projections even when the model/profile matches.
  Existing file transactions update generations and retire obsolete passages;
  content-addressed vectors remain reusable only for identical model/text inputs.

Four new regression cases cover non-UTF-8 input without NUL, faithful valid UTF-8
with an unknown extension, querying an existing V7 database, and rebuilding that
same database with a matching retrieval profile. The binary fixture is retained
as a file record but removed from the source catalog. The migration fixture
uses the real SQLite/indexing pipeline and a small supplied encoder to avoid
external model downloads. Removing the new projection validity condition in an
isolated source copy causes the migration test to fail; production files were
not mutated for that experiment.

Verification: 423 retrieval tests pass. The final complete suite exits0 with
15,047 passes and 10 expected xfails; receipt `verification.json` fixes the log hash.
The source fix and its tests were committed and pushed to `origin/main` without
changing package version or creating a release/tag. The 63 foreign modified-file
hashes and the 117-entry original status were preserved.

The registered V323 real Zig capture subsequently rebuilt 669 file records and
15,111passages, prepared 1,114 contextual source views per embedding and closed all
60 public API responses across CodeRank/Jina/Muninn with worker exit 0. This
establishes that the original preparation failure is repaired. Retrieval quality
is scored separately only after all 1,251 queries close for every embedding.

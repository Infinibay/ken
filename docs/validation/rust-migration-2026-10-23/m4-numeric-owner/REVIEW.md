# M4c1 final whole-plan review

Reviewer: `/root/m4c1_final_review`, fresh context, gpt-6-astra/high, read-only.
Range: 265a7e4d..0b19e877. One review; no re-review requested.

## Declined to judge

1. Public CLI/MCP, prepared production runtime, global deployment/resources: M4d/M5–M8.
2. Piece catalogs, requested-piece features/selection, physical source freshness: M4c2; piece forest loader included here.
3. Bit-identical static feature inputs: accepted upstream F32 bound requires exact production paths, leaves, scores, order, evidence, calls.
4. Strided/additional dtypes: interface owns contiguous F32/F64 matrices.
5. Live-file authentication of imported trace hashes: importer receives only trace/model; external source authority needed.

## Important findings

1. Canonical float spelling (rank_json.rs:45): Rust Debug selects601174747868153.3 while Python selects601174747868153.2 for the same F64 bits0x1.1161f3a5b5fcap+49. Python fingerprint786d21257be731b5fbe5a28ab63938c5c21e5510faef264f83163a4121f6f411; native d3f697d6541f92c46b1f7f6b069017c85862ef882859bc640bb920a2c47f8258. Five differences found among32768 targeted floats. Fix shortest-decimal ties, test both signs and neighbors. Registered forests unaffected in current captures.
2. Trace replay (ranking_trace.rs:202): two-feature owners with rows[1] and[2,3,4] silently flatten into[1,2]/[3,4]; matching scores/order can admit the malformed trace. Original NumPy rejects. Check each owner's width before flattening; test reproducing ragged case.
3. Process comparator (numeric_validate.py): generic1e-12 tolerance admits score1→1.0000000000001, also affects evidence/explanations/predictions. Default to exact; allow tolerance only at explicitly declared arithmetic/feature paths, including approved production feature bound. Test one-ULP tampering and replay preserved captures under strict comparator.

Critical: none.

## Minor finding

Python coercion/error edges: vertical-tab float whitespace rejected natively;10**400 raises native ValueError rather than original OverflowError; U+0080/U+00AD repr escaping differs. Uncommon model inputs/diagnostics; registered artifacts unaffected. Deferred.

## Strengths and assessment

Seven tasks follow coherent matrix/forest/arithmetic/coverage/source/ranking/trace/resource boundaries. Explicit dtype/BLAS dispatch, sequential accumulation, accurate explanations, generated licensed Snowball with bounded cache, streaming coverage, pre-encoding source guards, bounded lazy pinned resources and measured immutable fingerprint caching. Archived-source independent replay passed:78Rust/83tooling roots,35scoped original roots,861new cases plus758previous selection cases on both actual platforms;1066originals preserved. Acceptance correctly pending. No further defect found in arithmetic dispatch, ownership/cache, vocabulary limits, source admission or lazy production loading. Ready with the three Important fixes; perform one TDD pass and preserve declined/minor rulings.

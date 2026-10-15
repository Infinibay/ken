Independent review of source-prefix diagnostic87 — mapping and counts verified

All 400 original queries, 397 referenced-owner projections and 4,347 anchor-line assignments were independently checked against physical source, canonical source7 passages, exact69 projection strings/hashes and tokenizer offsets. All 171 input bindings and the frozen85b receipt match. Null alternatives enumerate individual same-file owners covering every original anchor span; child gaps are preserved. Missing owners/lines remain explicit. No source inference, fit, regrading or private-reserve access occurred.

| Original outcome subset | Queries | Complete mapped body-anchor prefix | All body anchors owned but beyond prefix | Not all anchors mapped to body |
|---|---:|---:|---:|---:|
| All | 400 | 325 | 15 | 60 |
| Strict hits | 286 | 230 | 9 | 47 |
| Wrong identity | 102 | 87 | 5 | 10 |
| Correct identity, strict miss | 12 | 8 | 1 | 3 |
| Wrong identity, implementation purpose | 90 | 79 | 4 | 7 |

The last row splits into EN 57 (53/2/2) and ES 33 (26/2/5). The original rows and summaries reproduce exactly. A check of whitespace-only anchored lines found no owner classification that changes when such lines are treated as vacuously visible.

The precise scope is physical lines mapped from `OwnerDescription.implementation`, which is the body. The actual69 implementation input also contains its synthetic path/identity/signature header. A declaration missing from the mapped body can therefore already occur in that same encoder input's header; documentation can occur in contract/fullowner. The 60 last-column cases do not establish absence from the input or index. Their 47 existing strict hits demonstrate why this cannot be an accuracy ceiling. The report's original field names are retained, with this interpretation made explicit.

Character endpoints establish that mapped source lines fit before the last non-special token's offset, under the same512 tokenizer truncation. Bert normalization lowercases/normalizes text, so this is availability within a source prefix, not lossless character-to-token reproduction. Complete anchor lines in that prefix do not prove semantic discrimination or explain a ranking mistake. The four implementation-purpose wrong-identity cases with complete body anchors beyond the prefix are concrete availability witnesses, not predicted recoverable hits. No benefit or quality claim for additional windows follows from this diagnostic.

Full binding hashes, per-owner witnesses and EN/ES/purpose strata are in [the mechanical report](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/source-prefix-diagnostic-v87-review.json).

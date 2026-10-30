# Portable historical test fixtures

These are test/example inputs, not release receipts or new acceptance evidence. Each gzip expands byte-for-byte to the named existing original JSON; no output, number, tolerance, platform, case order or hash was rewritten. No original/inference/model/global suite was replayed. `PROVENANCE.json` records both compressed and raw identities. Source originals remain unchanged in the ignored archival tree.

| Fixture | Compressed bytes | Original source | Raw SHA256 |
| --- | ---: | --- | --- |
| `model-policy-cases.json.gz` | 9631 | `docs/validation/rust-migration-2026-10-19/m2-policy/cases.json` | `0c4a8fbb46611c29bd1950cbc31114ceedc6a147af41e7138376b645d66ce46f` |
| `model-policy-reference.json.gz` | 31885 | `docs/validation/rust-migration-2026-10-19/m2-policy/reference.json` | `423c12a899c9acc7220c57c83d374bc47b3a178f140fd1264544058b3662e456` |
| `context-reference.json.gz` | 424681 | `docs/validation/rust-migration-2026-10-18/m2-context/reference.json` | `343fd57f5f644beff252260784fca165d2edf0ab8f38319815f2b0357b181af6` |
| `ettin-reference.json.gz` | 21550 | `docs/validation/rust-migration-2026-10-19/m2-ettin/reference.json` | `ddbd13c1e29d8a4f689b58cb9041aa0fcea4745618f065423ddf7dbe4cf7824b` |
| `translation-reference.json.gz` | 29594 | `docs/validation/rust-migration-2026-10-19/m2-translation/reference.json` | `f4e06db941dd706b0dee406ab8861fa5581219ccd6b5a5071e0a6bf7a2d89c1b` |
| `translation-raw-reference.json.gz` | 7951 | `docs/validation/rust-migration-2026-10-19/m2-translation/raw-reference.json` | `52aba5a994da4505a9ba3fe2d17264a72c693ca387415c2545ee026d30cbf92c` |
| `potion-reference.json.gz` | 32429 | `docs/validation/rust-migration-2026-10-18/m2-static/potion-reference.json` | `3c6c3295f97b6671dd6e00135117a276a53ce00489aa6dcfd4ba88cafb24443c` |
| `static-table-reference.json.gz` | 251975 | `docs/validation/rust-migration-2026-10-18/m2-table/reference.json` | `b2ed77496c6cf5df43dd43dd9eb3b904b60a71c9e1650f879b3428fa926e62f3` |

Callers still require their explicitly registered model/runtime resources where they did before. In particular, these fixtures do not claim M4/model/global acceptance, and the separate x86 contextual/Ettin profile originals and existing consumption hash checks are unchanged.

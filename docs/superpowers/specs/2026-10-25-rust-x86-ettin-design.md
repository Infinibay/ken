# Ettin histories on Linux x86_64

Continue the authorized Rust migration and x86_64 support inline on the migration
branch. This bounded change makes the existing registered Ettin test consume an
actual own-host observation. Currently every Linux host borrows Linux/aarch64.
The production scorer, source/compiler recipe and score tolerances stay unchanged.

The test-private original selector owns exact supported OS/architecture selection
and fixture integrity. The existing registered-history test owns inference and
comparison through public OnnxReranker. Caller: select the actual host, authenticate
the reference bytes, prepare the pinned source and compare all23 fixed histories.
Unknown or crossed targets fail before inference. No new product dependency/API.

Use a separate consumed x86 fixture, retaining the historical ARM document bytes.
An OS-only lookup silently borrows another architecture; a general model-oracle
framework would exceed this single test consumer. A small test-private selector
is the chosen implementation, following the existing contextual test convention.
Put hash verification at consumption, rather than relying on a separate test.

Original preparation preceded selector implementation:667940bytes, SHA256
ec1a7477107da440828fd0f46ab2c6d9be45a5d64c7c516306797aa2636e20ce.
All23 frozen-Python histories and24 original scoped tests passed. Reuse this
capture without repeating or rewriting it; keep original SDK/raw/source local.
Preserve fixed cases, graph bytes, policies and atol1e-5/rtol1e-5.

Validation: observe a missing-selector test RED; verify exact three-host metadata,
identical23cases and source definitions, unsupported pairs, and pinned bytes.
Run all existing Ettin native roots using real x86 source/core, strictfmt/Clippy,
and an input-only native23-history experiment with owned source/core outside the
checkout. One fresh scoped final review, one Important repair pass, no re-review.
This verifies the x86 Ettin test and experiment only; no complete M2/M3/index/M4
or three-host model acceptance, and no waiver for the independent ARM context drift.

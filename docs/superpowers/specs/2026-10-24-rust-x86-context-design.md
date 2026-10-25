# Contextual model parity on Linux x86_64

The user requests Linux x86_64 support for the migrated engine. CPU cores are
accepted at ece7a0c6; grammar/BLAS prerequisites are accepted. This slice makes
its existing production contextual model test use an actual same-host original
rather than reject x86 or borrow ARM observations. It does not accept all M2,
indexing or M4. The model implementation and numerical limits do not change.

Concepts: an architecture-bound original owns expected observations; native
ContextEncoder owns execution and compatible model identity; the existing
history comparator owns exact token/lazy/provider checks and bounded vectors.
A test-private selector owns the three explicitly supported original identities.
Caller: select the current host's original, verify pinned production weights,
then run the existing twenty histories through the public ContextEncoder API.
Unknown targets or a crossed original must fail before numerical acceptance.

Original preparation already happened before this change. Preserve and reuse
.ken/rust-migration/x86-context/context-original.json,935725bytes,
SHA b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733.
It is an actual frozen-Python Linux/x86_64 capture of the same20 fixed histories,
with4original scoped tests PASS. A separate input-only native experiment matched
all20 with unchanged bounds and oneexec/no connect. No repeat capture is allowed.
Only the consumed fixture enters Git; raw/SDK/weights/receipts stay local.

Use a bounded JSON fixture without a new dependency. Preserve accepted ARM
reference bytes and paths, existing case order, atol/rtol/cosine bounds and public
model APIs. Validate host identity and fixture integrity before using observations.
Keep unsupported architecture failure explicit. The next model should be able to
add its own reference locally; do not introduce a generic oracle framework for
one test consumer. No install,merge,release or historical receipt rewrites.

Validation: witness the existing x86 architecture guard RED with actual prepared
weights/core. Add source/host/case/integrity guards RED before implementing the
selector. Run complete contextual native tests on x86 with real production
weights, actual authenticated ORT, existing synthetic tests and strictfmt/Clippy.
Retain fresh native execution against the reused original and complete matching
source/tooling records. Reuse accepted ARM originals and require directly affected
regressions. One fresh final read-only reviewer and one Important/Critical TDD
repair pass, no implementation agents/no second review or stage permission menu.
Only contextual x86 capability may close; full M2x86/M3x86/M4/global stay pending.

# Native query expansion on Linux x86_64

Continue the approved full migration autonomously, focused on Linux x86_64.
BestSearch's independent SkylakeX comparison remains open; it does not prevent
implementing this separate model capability. Nothing in this slice accepts that
unresolved score or changes a previous numerical reference.

## Responsibility and use

`LocalQueryExpansion` already owns lazy translation, prepared assets, tokenization,
one synchronized native translator and per-call diagnostics. Keep that owner and
its public interface: `expand`, `expand_attempt`, `load`, `runtime_identity`.
`ModelFactory` continues to supply the deferred registered source. A public caller
constructs an engine without resources, passes English without acquisition,
translates Spanish while protecting code identifiers, and reuses its one replica.
`RegisteredSearchResources` must be able to warm Spanish on the actual x86 CPU.

The current runtime rejects x86 before loading; the integration oracle and probe
also select ARM only. Enable Linux x86 using the existing pinned CT2/Ruy/OpenBLAS
build and choose an independently frozen x86 oracle. Do not make ARM observations
the expected output for this architecture or change the backend to obtain a pass.
If the existing backend differs from the independent original, investigate the
actual native arithmetic/configuration before choosing a correction.

## Chosen approach

Extend the existing translation owner and preparation rather than add a second
translator. Preserve original ARM behavior and all public return values. The
alternative of delegating to Python cannot satisfy native migration; silently
reusing ARM text/hypotheses would hide the platform constraint.

Observe the existing 29 complete original translation histories once on x86,
including token boundaries, code placeholders, Unicode, repeated calls, missing
and corrupt assets, and recovery. Add optional immediate journaling to the shared
observer without changing the default capture contract. Retain stdout/stderr and
all partial records if an observation fails; an accepted row is never recaptured.
The raw-core x86 test consumes the actual prepared text/tokens/hypotheses already
present in these observations, avoiding a duplicate original inference corpus.

Use a compact gzip fixture with strict source/runtime/recipe/artifact/inventory
authentication. Tests select by actual OS/architecture and reject crossed or
ambiguous expectations. Existing ARM fixtures remain byte-identical.

## Evidence and boundaries

- Frozen1066input fingerprint: `5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`.
- Rust1.95.0; CT2RS0.10.1/CT2source4.8.2; SentencePiece0.13.2/source0.2.1;
  Python3.12.9, original CT2wheel4.8.2/SP0.2.1 and Unicode15.0.
- Native CPU int8, Ruy, two intra threads, one replica, beam1, input1024/output256;
  Linux floating backend OpenBLAS0.3.26, prepared CORE2 LP64 archive on x86.
- No new external versions, old original/model/quality/tolerance changes, private
  reserves, original pytest runs, installed-app replacement, merge or release.
- Reuse the input-only native `translation_probe`, strict `compare_output`, source
  verification and confinement. A new x86 host owner must not invoke the original
  again during verification, unlike the historical compare-and-recapture driver.
- Prove actual Cargo-selected native build settings, registered assets, native
  execution outside checkout, no Python/child/network and complete case inventory.
- Run affected model/search suites, all model units, fmt and strict Clippy, then
  local and two CI x86 qualification; preserve every failed attempt.
- Archive source-bound raw evidence locally, keep Git free of generated receipts,
  commit/push the authorized branch. M4/global remains open for its other gates.

These are executor choices under the user's explicit autonomy instruction; the
global migration contract remains the authority for public compatibility.

## Evidence-based x86 core adjustment

The independent x86 original produced `Look for the class...`; the first native
Ruy implementation produced `Find the class...` with identical prepared tokens.
An original constructor-only trace reports oneDNN for both CPU GEMMs on AMD.
A standalone C++ executable using the pinned original CT2 4.8.2 core reproduces
the frozen hypotheses exactly without Python. Preserve that independent fixture.

Use that registered pure-native CPU core for x86 through a small versioned C ABI
module, following the existing explicit lazy native-runtime ownership pattern.
The module forwards the policy owned by Rust and reports the actual selected
oneDNN/MKL backend; it never calls a Python interpreter. Authenticate module,
CT2 core and OpenMP sidecar before loading private immutable copies. Session
handles retain the module/files until after native destruction. Token spans and
owned output buffers preserve lengths, embedded NUL and UTF8 across the boundary.

Add `NativeTranslationRuntime` and an explicit `with_native_runtime` collaborator
to LocalQueryExpansion; ModelFactory obtains it from PreparedModelResources.
Parsing remains cold and failed acquisition remains retryable. ARM keeps its
existing CT2RS/Ruy implementation and serialized identity. x86 diagnostics name
the actual native binding/core/backend instead of claiming CT2RS/Ruy.

Prepare the core from the already pinned CT2 4.8.2 wheel and headers from the
already pinned CT2RS 0.10.1 source archive, preserving licenses. No external
version changes are required. Extend Task2 with SDK/ABI/owner tests before
production wiring. The earlier Ruy/OpenBLAS-only x86 assumption is superseded by
this experimentally justified correction; it remains the ARM contract.

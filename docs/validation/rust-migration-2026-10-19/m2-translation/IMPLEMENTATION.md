# Native translation implementation record

Continues codex/rust-migration after accepted Ettin1ae4bb97. Overall M2 and the
whole application migration remain open. Original sources/resources/tests and
installed application are preserved. Both platform26gate validation and the current-source matrix now pass. The
final fresh whole-plan review remains pending.

Design: docs/superpowers/specs/2026-10-19-rust-translation-design.md.
Plan: docs/superpowers/plans/2026-10-19-rust-m2-translation.md.

## Independent groundwork

The disposable Rust/C++ probe compiled and executed on macOS arm64 and Linux
aarch64 without Python dependencies. It matched all24 original raw token/piece/
hypothesis/text/error histories after using the original platform's float GEMM
backend, in addition to Ruy int8: Accelerate on macOS; static OpenBLAS0.3.26 and
OpenMP COMP on Linux. VIABILITY.json records versions, binary hashes, dependency
names, OpenBLAS source/library hashes and build flags. Failed Ruy-only runs and
all build/preparation attempts are retained privately. No temporary probe code
is a substitute for the planned native library, process and26gate proof.

Original package versions are macOS CT24.8.3/Linux CT24.8.2 and SPM0.2.1; compiled
Rust probe CT24.8.2/SPM0.2.1 are reported separately. Original source/prepared five
artifact hashes and original owner-module hashes agree between platforms.

The original model has512positions despite generic max_input_length1024.
Both original platforms reject513tokens and expose the same1024input truncation
boundary, but their repeated-token511/512translations differ. Per-platform
oracles preserve those differences; no text tolerance or whitelist hides them.

cases.json fixes29 original query histories, captured before native product
implementation on both platforms in reference.json. They include missing/corrupt
data laziness, exact source token boundaries, load/error/recovery state, protected
code, Unicode/emoji/NUL/newlines and repeated calls. Real traces wrap the actual
original CT2/SPM and retain prepared strings, source IDs/pieces, hypotheses,
decoded/restored text, timing, raw/observed peak histories and original identity.

The original-only policy fixture covers2438 deterministic histories and controlled
restoration through the actual original query-expansion owner. Controlled decoder
outputs are explicitly labelled policy-only. Separate Unicode15.0.0 data verifies
every valid scalar against Python regex word/digit/space predicates and freezes
the full casefold/predicate digest
ade25dd6e59cf7919537e19af9070770bd3ec5ea50b5ad98c6948ea2ff495777.
Tiny preparation bytes come from the frozen original test helper with its SHA;
they are preparation-only and do not masquerade as a working neural model.

The native text-policy slice now passes the2438 original histories, six original
controlled restoration cases, independent-plan/sequential-collision checks, all38
original lexicon members and the whole-scalar Unicode digest (four integration
tests plus one unit test). Workspace formatting and ken-models all-target clippy
pass.

Native model registration, exact legacy identities and atomic preparation now
pass13 public-usage tests on both platforms. This includes the real five-file
derivation, cache reuse without upstream, owned snapshots after replacement,
simultaneous publishers, failed publication, ordinary permissions, nonregular
input and ordered nested JSON/Unicode/integer boundaries. Two recipe-hash tests
first reproduced missing recursive Python array formatting in the shared helper;
the focused array fix made them pass without changing established object order.
The complete Rust workspace reports125 passes on each platform, no failures or
ignored tests; both workspace fmt and all-target clippy pass. TASK2.json records
the immutable input fingerprint and raw-log hashes. The13 original/oracle Python
tests and original1066-file integrity check also pass.

Tasks2 and3 are complete. Native CTranslate2 runtime integration and both
platform26gate verification now pass; the final review is pending and M2 is open.

Python sanity verification passes15651 tests with the same10 historical xfail
IDs, no original baseline test IDs lost. The initial restricted diagnostic run
was interrupted after three unchanged KQL-service tests could not bind local
sockets; their worker logs confirmed PermissionError. All three passed with
the required local-socket permission, followed by the complete passing suite.
No original source/test/timeout was changed. Seven new oracle tests and six
original translation tests also passed the Task1 completion command.

## Native runtime implementation

LocalQueryExpansion owns one lazy, serialized CTranslate2/SentencePiece session.
The session materializes all five authenticated artifacts into a retained private
directory and loads SentencePiece from authenticated serialized bytes. It keeps
the directory alive until after the native model and workers are destroyed.
English passthrough returns before loading or filesystem work; loading failures
remain retryable. Initialized models and returned diagnostics own their data,
including after source/cache paths are replaced.

expand_detailed returns per-call prepared text, token IDs/pieces, actual native
hypotheses and decoded/restored text; expand consumes that same operation. The
native identity distinguishes compiled CT24.8.2/SPM0.2.1, configured CPU/int8
policy and platform GEMM backends from the observed single native replica. It
does not report the original Python package versions as executing Rust versions.

Five public integration tests exercise all29 original histories, independent
returned results, simultaneous first calls, failure/retry and cache replacement.
A private-core test additionally exercises the original24 raw histories through
the same product translation method, including raw inputs outside the public
Spanish language gate. The exact per-platform expectations remain unchanged.

The initial default C++ Debug build changed the511-token question-prefix greedy
translation on macOS. A controlled run of the same product in Release matched
all29 histories. Keeping only ct2rs optimized in the ordinary Rust dev/test
profile then passed all five public tests. Cargo.toml therefore pins that native
core to Release via opt-level3/debugfalse; Rust overflow and assertion checks
remain enabled. Actual CMake caches confirm Release with Accelerate/Ruy on
macOS and OpenBLAS/Ruy/OpenMP COMP on Linux. This costs C++ build time and native
debug information; removing the override invalidates the demonstrated parity.

The final Task3 implementation passes the complete131-test Rust workspace on
each registered platform, with zero failures or ignored tests. Formatting and
all-target Clippy pass on both platforms; the13 original/oracle Python tests and
the original1066-file integrity check pass. TASK3.json binds the immutable tested
input fingerprint, actual CMake policies and full log hashes. These are runtime
implementation checks; the independent process and composed26gate acceptance
are the next task.

## Independent process and composed validation

The native JSON probe executes the actual preparation and expansion owners. It
contains no expected translations. Both platform histories match the original
source tokens, hypotheses, final text, errors and lazy/retry state exactly. Each
process uses independent data and a copied executable outside the checkout with
sentinel PATH; Linux records exactly one exec. Native dependencies are audited,
including static CT2/SPM/OpenBLAS and the explicit Linux system OpenMP runtime.
Actual native identities, Cargo-selected build directories, CMake3.31.10 compiler
and Release/backend flags bind the proof to the executed source and executable.

macOS arm64 and Linux aarch64 each pass all26 gates,132 Rust tests (zero failed or
ignored),15670 Python tests and the same10 historical xfail IDs. No baseline IDs
are lost and no new skips or type errors appear. All1066 originals match their
pre-migration hashes. MATRIX.json binds all24 current source/input fingerprints
and reports Translation_accepted=true,M2_accepted=false. The fresh final review
still gates closure of this profile.

The first Linux full attempt is retained as failed: cold test compilation plus
execution exceeded the unchanged600s gate; host filesystem pressure also caused
EIO writing private prepared models. Only our disposable target/debug cache was
removed, preserving source, originals, models and release binaries. A100MB fsync
probe and both actual model process smokes then passed. Precompiling test binaries
before the gate took compilation out of its execution budget; the complete retry
passed with the same tests, expectations and600s limit. CI now prepares those
binaries explicitly, but no remote CI execution is claimed.

The public platform directories retain full summary/logs, measured timings and
raw/observed memory histories, plus manifests hashing all private raw evidence.
The raw evidence and failed attempts remain in .ken; model weights and disposable
environment caches are excluded from version control. No speedup or memory SLA
is claimed. expand_attempt owns the actual encoded input even on inference
failure; no failed-case trace is reconstructed by re-tokenizing later.

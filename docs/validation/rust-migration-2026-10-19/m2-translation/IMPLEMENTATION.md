# Native translation implementation record

Continues codex/rust-migration after accepted Ettin1ae4bb97. Overall M2 and the
whole application migration remain open. Original sources/resources/tests and
installed application are preserved. This record does not certify a native
translation product implementation yet.

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
pass. Model registration/preparation/runtime and final26gate acceptance remain
pending; this is not completion of Task2 or the profile.

Python sanity verification passes15651 tests with the same10 historical xfail
IDs, no original baseline test IDs lost. The initial restricted diagnostic run
was interrupted after three unchanged KQL-service tests could not bind local
sockets; their worker logs confirmed PermissionError. All three passed with
the required local-socket permission, followed by the complete passing suite.
No original source/test/timeout was changed. Seven new oracle tests and six
original translation tests also passed the Task1 completion command.

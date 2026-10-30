# Private transformer namespace fixture

These four tiny C sources are authored native loader fixtures, not Torch SDK
substitutes or model qualification data. `marker.c` is compiled twice with one
SONAME and different return values. `bridge.c` makes dependency ordering differ
from filename ordering. `module.c` admits its real C ABI table only with the
private marker, and allocates/releases its result buffers within that module.

The Rust test starts a child with launcher-style `LD_LIBRARY_PATH` and preloads
the other marker globally. This preserves the startup dynamic-loader search
environment and checks that the base namespace remains unchanged. `repro.c`
additionally distinguishes ordinary dlopen, bare NEWLM, and explicitly pinned
dependency-first NEWLM loading without compiling Rust or loading any SDK/model.

This checks symbol binding and C ABI ownership only. Real Torch initialization,
TLS use, CPU execution, and shutdown require the separate authenticated SDK
closure probe. No expected SDK bytes or model numerical contracts change here.

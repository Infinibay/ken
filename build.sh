#!/usr/bin/env bash
# Build the `ken` release binary.
#
# Requirements: Rust toolchain via rustup (https://rustup.rs).
# Build deps on Linux: a C toolchain (gcc + libstdc++ headers) for ort/onnxruntime
# (fastembed) and openssl-dev for the rustls fallback. Most distros have these
# under `build-essential` / `base-devel`.

set -euo pipefail

# Source the user's cargo env if cargo isn't already on PATH (rustup installs
# there but may not have updated the current shell yet — common on a fresh box).
if ! command -v cargo >/dev/null 2>&1; then
    if [ -f "$HOME/.cargo/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.cargo/env"
    fi
fi

if ! command -v cargo >/dev/null 2>&1; then
    echo "error: cargo not found." >&2
    echo "Install Rust first: https://rustup.rs (curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh)" >&2
    exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"

echo "→ cargo build --release -p ken (with default features: postgres, fastembed, code, pdf, git)"
cargo build --release -p ken

bin="target/release/ken"
if [ ! -x "$bin" ]; then
    echo "error: build finished but $bin not found" >&2
    exit 1
fi

echo
echo "✓ built $bin"
echo "  size: $(du -h "$bin" | cut -f1)"
echo "  ./$bin --help    # see subcommands"
echo
echo "Next: ./install.sh    # to install to ~/.cargo/bin/ken"

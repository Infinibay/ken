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

# CUDA auto-detect. Three positive signals; any one is enough to opt in:
#   1. `nvidia-smi` is on PATH and reports a GPU (the canonical check).
#   2. `/dev/nvidia0` exists (driver loaded even if smi is missing).
#   3. Caller forced it via KEN_BUILD_CUDA=1.
# Override with KEN_BUILD_CUDA=0 to opt out even on a GPU host (useful when
# the host has a GPU but you want a portable CPU-only artefact).
detect_cuda() {
    case "${KEN_BUILD_CUDA:-}" in
        1|true|yes) return 0 ;;
        0|false|no) return 1 ;;
    esac
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
        return 0
    fi
    [ -e /dev/nvidia0 ] && return 0
    return 1
}

features=""
if detect_cuda; then
    features="--features cuda"
    echo "→ NVIDIA GPU detected — building with --features cuda"
    echo "  (override with KEN_BUILD_CUDA=0 to force a CPU-only build)"
else
    echo "→ No NVIDIA GPU detected — building CPU-only"
    echo "  (override with KEN_BUILD_CUDA=1 to force a CUDA build)"
fi

echo "→ cargo build --release -p ken $features"
# shellcheck disable=SC2086
cargo build --release -p ken $features

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

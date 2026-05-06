#!/usr/bin/env bash
# Build + install `ken` to ~/.cargo/bin so it's on PATH everywhere.
# Idempotent: re-running upgrades the binary in place. Cleans up legacy
# binaries from the pre-rename `cae-claude` / `context-engine` era if it
# finds them.

set -euo pipefail

if ! command -v cargo >/dev/null 2>&1; then
    if [ -f "$HOME/.cargo/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.cargo/env"
    fi
fi

if ! command -v cargo >/dev/null 2>&1; then
    echo "error: cargo not found." >&2
    echo "Install Rust first: https://rustup.rs" >&2
    exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"

echo "→ cargo install --path crates/ken --force (release build, all default features)"
cargo install --path crates/ken --force

# Sweep up legacy binaries from before the project rename. Harmless if absent.
for legacy in cae-claude context-engine; do
    legacy_path="$HOME/.cargo/bin/$legacy"
    if [ -f "$legacy_path" ]; then
        echo "→ removing legacy binary $legacy_path"
        rm -f "$legacy_path"
    fi
done

ken_path="$(command -v ken || true)"
if [ -z "$ken_path" ]; then
    echo
    echo "✓ installed, but \`ken\` is not on your current shell's PATH."
    echo "  Make sure ~/.cargo/bin is on PATH, e.g.:"
    echo "    fish:  set -gx PATH \$HOME/.cargo/bin \$PATH"
    echo "    bash:  echo 'export PATH=\"\$HOME/.cargo/bin:\$PATH\"' >> ~/.bashrc"
    echo "    zsh:   echo 'export PATH=\"\$HOME/.cargo/bin:\$PATH\"' >> ~/.zshrc"
    exit 0
fi

echo
echo "✓ installed $ken_path"
ken --help | head -1
echo
echo "Next steps:"
echo "  1. Run the engine server. Easiest path (auto-starts Postgres in docker/podman):"
echo "       ken serve --with-pg"
echo "     Or manage Postgres yourself:"
echo "       docker-compose up -d"
echo "       export DATABASE_URL=postgres://cae:cae_dev@localhost:5432/context_engine"
echo "       ken serve"
echo "  2. In each project where you want Claude Code wired up:"
echo "       cd /path/to/project"
echo "       ken install --workspace 1"
echo "       # restart Claude Code in that directory"

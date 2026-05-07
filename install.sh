#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh [--project PATH] [--codex] [--no-bootstrap-uv]

Installs the ken CLI from this checkout using uv:

  uv tool install --from <repo> ken --force

Options:
  --project PATH      After installing the CLI, run `ken install PATH`.
  --codex             Pass `--codex` to `ken install` when --project is used.
  --no-bootstrap-uv   Fail if uv is not already installed.
  -h, --help          Show this help.
EOF
}

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_path=""
codex_flag=()
bootstrap_uv=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      if [[ $# -lt 2 ]]; then
        echo "install.sh: --project requires a path" >&2
        exit 2
      fi
      project_path="$2"
      shift 2
      ;;
    --codex)
      codex_flag=(--codex)
      shift
      ;;
    --no-bootstrap-uv)
      bootstrap_uv=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "install.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  if [[ "$bootstrap_uv" -eq 0 ]]; then
    echo "install.sh: uv is not installed; install uv or omit --no-bootstrap-uv" >&2
    exit 1
  fi
  echo "uv not found; installing uv with Astral's official installer..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "install.sh: need curl or wget to install uv" >&2
    exit 1
  fi
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

echo "Installing ken from $repo_root..."
uv tool install --from "$repo_root" ken --force

if ! command -v ken >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if command -v ken >/dev/null 2>&1; then
  ken --version
else
  echo "install.sh: ken installed, but it is not on PATH." >&2
  echo "Add ~/.local/bin or ~/.cargo/bin to PATH, then run: ken --version" >&2
  exit 1
fi

if [[ -n "$project_path" ]]; then
  echo "Wiring ken into project: $project_path"
  ken install "$project_path" "${codex_flag[@]}"
fi

echo "Done."

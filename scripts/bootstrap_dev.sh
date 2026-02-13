#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_UV="${INSTALL_UV:-0}"

print_uv_help() {
  cat >&2 <<'HELP'
error: uv is not installed or not available in PATH.

Install uv with one of:
  curl -LsSf https://astral.sh/uv/install.sh | sh
  wget -qO- https://astral.sh/uv/install.sh | sh
  brew install uv
  pipx install uv

If uv was installed to ~/.local/bin, add it to PATH:
  export PATH="$HOME/.local/bin:$PATH"

To let this script attempt automatic install, run:
  INSTALL_UV=1 bash scripts/bootstrap_dev.sh
HELP
}

ensure_uv_available() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  if [[ "${INSTALL_UV}" != "1" ]]; then
    print_uv_help
    exit 1
  fi

  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "error: INSTALL_UV=1 requested, but neither curl nor wget is available." >&2
    exit 1
  fi

  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv installation completed but uv was not found in PATH." >&2
    echo "hint: add ~/.local/bin to PATH and rerun this script." >&2
    exit 1
  fi
}

ensure_uv_available
cd "${PROJECT_ROOT}"
uv sync --extra dev

cat <<'EOF'
bootstrap complete.

Next steps:
  make run
  make test
EOF

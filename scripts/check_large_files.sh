#!/usr/bin/env bash
set -euo pipefail

LIMIT_MB="${LARGE_FILE_LIMIT_MB:-95}"

if [[ ! "${LIMIT_MB}" =~ ^[0-9]+$ ]] || [[ "${LIMIT_MB}" -le 0 ]]; then
  echo "error: LARGE_FILE_LIMIT_MB must be a positive integer (got: ${LIMIT_MB})" >&2
  exit 1
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "error: this command must be run inside a git repository" >&2
  exit 1
fi

limit_bytes=$((LIMIT_MB * 1024 * 1024))
declare -a offenders=()

while IFS= read -r -d '' path; do
  [[ -f "${path}" ]] || continue
  size_bytes="$(wc -c < "${path}")"
  if (( size_bytes > limit_bytes )); then
    size_mb="$(awk -v bytes="${size_bytes}" 'BEGIN { printf "%.2f", bytes/1024/1024 }')"
    offenders+=("${path} (${size_mb} MB)")
  fi
done < <(git ls-files -z)

if (( ${#offenders[@]} > 0 )); then
  echo "error: tracked files exceed ${LIMIT_MB} MB:" >&2
  for item in "${offenders[@]}"; do
    echo "- ${item}" >&2
  done
  echo "hint: remove or untrack large artifacts, or use Git LFS where appropriate." >&2
  exit 1
fi

echo "ok: no tracked files exceed ${LIMIT_MB} MB"


#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COSIGN_VERSION="${COSIGN_VERSION:-v2.2.4}"
COSIGN_INSTALL_DIR="${COSIGN_INSTALL_DIR:-${PROJECT_ROOT}/.tools/bin}"
COSIGN_DOWNLOAD_BASE_URL="${COSIGN_DOWNLOAD_BASE_URL:-https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}}"
COSIGN_FORCE_INSTALL="${COSIGN_FORCE_INSTALL:-0}"

usage() {
  cat <<USAGE
Usage: $(basename "$0")

Install cosign into a local tools directory for production image signature checks.

Options via env:
  COSIGN_VERSION            Version tag (default: ${COSIGN_VERSION})
  COSIGN_INSTALL_DIR        Install directory (default: ${COSIGN_INSTALL_DIR})
  COSIGN_DOWNLOAD_BASE_URL  Download base URL (default: GitHub release for COSIGN_VERSION)
  COSIGN_FORCE_INSTALL      Reinstall even if binary already exists (default: 0)
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 0 ]]; then
  usage >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "error: curl is required to install cosign" >&2
  exit 1
fi

cosign_path="${COSIGN_INSTALL_DIR}/cosign"
if [[ -x "${cosign_path}" && "${COSIGN_FORCE_INSTALL}" != "1" ]]; then
  echo "cosign already installed at ${cosign_path}"
  exit 0
fi

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "${os}" in
  linux|darwin) ;;
  *)
    echo "error: unsupported operating system for cosign install: ${os}" >&2
    exit 1
    ;;
esac

arch="$(uname -m)"
case "${arch}" in
  x86_64|amd64) arch="amd64" ;;
  arm64|aarch64) arch="arm64" ;;
  *)
    echo "error: unsupported architecture for cosign install: ${arch}" >&2
    exit 1
    ;;
esac

artifact="cosign-${os}-${arch}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

binary_path="${tmpdir}/${artifact}"
checksums_path="${tmpdir}/cosign_checksums.txt"

curl -fsSLo "${binary_path}" "${COSIGN_DOWNLOAD_BASE_URL}/${artifact}"
curl -fsSLo "${checksums_path}" "${COSIGN_DOWNLOAD_BASE_URL}/cosign_checksums.txt"

expected_checksum="$(awk -v file_name="${artifact}" '$2==file_name{print $1}' "${checksums_path}")"
if [[ -z "${expected_checksum}" ]]; then
  echo "error: unable to find checksum for ${artifact}" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  echo "${expected_checksum}  ${binary_path}" | sha256sum -c - >/dev/null
elif command -v shasum >/dev/null 2>&1; then
  echo "${expected_checksum}  ${binary_path}" | shasum -a 256 -c - >/dev/null
else
  echo "error: missing checksum tool; install sha256sum or shasum" >&2
  exit 1
fi

mkdir -p "${COSIGN_INSTALL_DIR}"
install -m 0755 "${binary_path}" "${cosign_path}"

echo "installed cosign ${COSIGN_VERSION} at ${cosign_path}"

#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[demo] starting first-success flow"
echo "[demo] this will run the full local smoke scenario in a temporary workspace"
bash "${PROJECT_ROOT}/scripts/smoke.sh"
echo "[demo] success: core API, autopilot, job queue, webhook, and metrics flow validated"

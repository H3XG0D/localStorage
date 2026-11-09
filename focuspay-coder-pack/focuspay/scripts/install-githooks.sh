#!/usr/bin/env bash
# Point this clone at repo-managed hooks (pre-push runs scripts/check.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
git -C "$ROOT" config core.hooksPath .githooks
chmod +x "$ROOT/.githooks/pre-push" "$ROOT/scripts/check.sh"
echo "hooksPath=.githooks (pre-push -> scripts/check.sh)"

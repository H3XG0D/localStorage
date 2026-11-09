#!/usr/bin/env bash
# Fail if known GPL/AGPL modules appear as direct require, or amneziawg-go pin drifts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "license-check FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> license-check"

[[ -f NOTICE.md ]] || fail "NOTICE.md missing"
[[ -f THIRD_PARTY_LICENSES.md ]] || fail "THIRD_PARTY_LICENSES.md missing"
grep -qi 'amneziawg-go' NOTICE.md || fail "NOTICE must mention amneziawg-go"
grep -qi 'amneziawg-go' THIRD_PARTY_LICENSES.md || fail "THIRD_PARTY_LICENSES must mention amneziawg-go"
grep -qi 'wireguard-go\|golang.zx2c4.com/wireguard' NOTICE.md || fail "NOTICE must mention wireguard-go"
grep -qi 'wireguard' THIRD_PARTY_LICENSES.md || fail "THIRD_PARTY_LICENSES must mention wireguard"
grep -qi 'Xray\|xray-core' NOTICE.md || fail "NOTICE must mention Xray"
grep -qi 'Xray\|xray' THIRD_PARTY_LICENSES.md || fail "THIRD_PARTY_LICENSES must mention Xray"
ok "NOTICE + THIRD_PARTY_LICENSES"

# Direct requires only (go.mod require block)
if grep -E '^\s+(github.com/amnezia-vpn/amnezia-client|github.com/SagerNet/sing-box)\s' go.mod; then
  fail "forbidden GPL module in go.mod require"
fi
ok "no forbidden GPL direct requires"

PIN="$(go list -m -f '{{.Version}}' github.com/amnezia-vpn/amneziawg-go 2>/dev/null || true)"
[[ "$PIN" == "v0.2.19" ]] || fail "amneziawg-go pin want v0.2.19 got ${PIN:-missing}"
ok "amneziawg-go pin $PIN"

WG="$(go list -m -f '{{.Path}}@{{.Version}}' golang.zx2c4.com/wireguard 2>/dev/null || true)"
[[ -n "$WG" ]] || fail "golang.zx2c4.com/wireguard missing from go.mod"
ok "wireguard-go present ($WG)"

# Linked into clients/appcore (not just planned)
grep -R --include='*.go' -l 'amneziawg-go/device' clients/appcore >/dev/null \
  || fail "appcore must import amneziawg-go/device"
grep -R --include='*.go' -l 'golang.zx2c4.com/wireguard/device' clients/appcore >/dev/null \
  || fail "appcore must import wireguard/device"
grep -R --include='*.go' -l 'clients/shared/xray' clients/appcore >/dev/null \
  || fail "appcore must use shared/xray (JSON path)"
# Must NOT statically link Xray-core into the product module
if go list -deps ./clients/appcore/... 2>/dev/null | grep -qiE 'github.com/xtls/xray-core|github.com/amnezia-vpn/amnezia-xray-core'; then
  fail "Xray-core must not be a Go dependency (subprocess + JSON only)"
fi
ok "appcore embeds amneziawg-go + wireguard-go; xray is JSON/subprocess only"

echo "license-check PASS"

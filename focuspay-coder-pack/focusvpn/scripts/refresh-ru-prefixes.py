#!/usr/bin/env python3
"""Refresh the RIPE RU prefix snapshot shipped in the Android client.

Source is the public RIPE NCC delegated stats file (country code RU), not a
GeoIP database. IPv4 rows store an address count; IPv6 rows store a prefix
length. Output is aggregated CIDRs, one per line.
"""

import ipaddress
import sys
import urllib.request
from datetime import date
from pathlib import Path

SOURCE = "https://ftp.ripe.net/ripe/stats/delegated-ripencc-latest"
OUT = Path(__file__).resolve().parents[1] / "clients/android/app/src/main/assets/ru-prefixes.txt"


def cidrs_from_delegated(text: str) -> list[str]:
    v4: list[ipaddress.IPv4Network] = []
    v6: list[ipaddress.IPv6Network] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 7 or parts[1] != "RU":
            continue
        if parts[6] not in ("allocated", "assigned"):
            continue
        kind, start, value = parts[2], parts[3], parts[4]
        if kind == "ipv4":
            count = int(value)
            first = ipaddress.ip_address(start)
            last = first + count - 1
            v4.extend(ipaddress.summarize_address_range(first, last))
        elif kind == "ipv6":
            v6.append(ipaddress.ip_network(f"{start}/{value}", strict=False))
    nets = list(ipaddress.collapse_addresses(v4)) + list(ipaddress.collapse_addresses(v6))
    return [str(net) for net in nets]


def main() -> int:
    with urllib.request.urlopen(SOURCE, timeout=60) as resp:
        text = resp.read().decode("utf-8", "replace")
    cidrs = cidrs_from_delegated(text)
    if len(cidrs) < 1000:
        print(f"refusing to write: only {len(cidrs)} prefixes", file=sys.stderr)
        return 1
    today = date.today().isoformat()
    header = (
        f"# RU prefixes from RIPE NCC delegated stats ({SOURCE})\n"
        f"# Snapshot {today}. Allocated and assigned resources with country RU.\n"
        "# Refresh: python3 scripts/refresh-ru-prefixes.py\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(header + "\n".join(cidrs) + "\n", encoding="utf-8")
    print(f"wrote {len(cidrs)} prefixes to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

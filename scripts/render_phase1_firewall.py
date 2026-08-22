#!/usr/bin/env python3
"""Render, but never apply, a least-privilege nftables Phase 1 ruleset."""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def cidrs(value: str) -> str:
    return ", ".join(str(ipaddress.ip_network(item.strip(), strict=False)) for item in value.split(","))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-cidrs", required=True)
    parser.add_argument("--sip-cidrs", required=True)
    parser.add_argument("--rtp-cidrs", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("firewall artifacts must be written outside the repository")
    rules = f"""# review before applying; this generator never changes the host firewall
table inet anshin_phone_phase1 {{
  chain input {{
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iifname \"lo\" accept
    ip saddr {{ {cidrs(args.admin_cidrs)} }} tcp dport 22 accept
    ip saddr {{ {cidrs(args.sip_cidrs)} }} udp dport 5060 accept
    ip saddr {{ {cidrs(args.rtp_cidrs)} }} udp dport 20000-20100 accept
    ip protocol icmp accept
  }}
}}
"""
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.write_text(rules, encoding="utf-8")
    output.chmod(0o600)
    print(f"rendered review-only ruleset: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render the Phase 1 Kamailio configuration from validated non-secret values."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re


TEMPLATE = Path("/opt/anshin-phone/templates/kamailio.cfg.template")
OUTPUT = Path("/tmp/kamailio.cfg")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
SOCKET_RE = re.compile(r"^udp:[A-Za-z0-9][A-Za-z0-9.-]{0,252}:[0-9]{1,5}$")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"{name} is required and must be one line")
    return value


def host(name: str) -> str:
    value = required(name)
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if not HOST_RE.fullmatch(value):
            raise ValueError(f"{name} must be an IP address or DNS hostname")
    return value


def port(name: str) -> str:
    value = required(name)
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError(f"{name} must be a valid port")
    return value


def cidrs(name: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    parsed = []
    for item in required(name).split(","):
        parsed.append(ipaddress.ip_network(item.strip(), strict=False))
    return parsed


def condition(networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> str:
    return " || src_ip ".join(f"== {network.with_prefixlen}" for network in networks)


def main() -> None:
    asterisk_networks = cidrs("ASTERISK_SOURCE_CIDRS")
    carrier_networks = cidrs("CARRIER_SOURCE_CIDRS")
    smartphone_networks = cidrs("SMARTPHONE_SOURCE_CIDRS")
    socket = required("RTPENGINE_SOCKET")
    if not SOCKET_RE.fullmatch(socket) or not 1 <= int(socket.rsplit(":", 1)[1]) <= 65535:
        raise ValueError("RTPENGINE_SOCKET must use udp:host:port")

    replacements = {
        "__SBC_ADVERTISED_IP__": host("SBC_ADVERTISED_IP"),
        "__SBC_EDGE_IP__": host("SBC_EDGE_IP"),
        "__SBC_INTERNAL_IP__": host("SBC_INTERNAL_IP"),
        "__ASTERISK_HOST__": host("ASTERISK_HOST"),
        "__ASTERISK_PORT__": port("ASTERISK_PORT"),
        "__RTPENGINE_SOCKET__": socket,
        "__ASTERISK_SOURCE_CONDITION__": condition(asterisk_networks),
        "__CARRIER_SOURCE_CONDITION__": condition(carrier_networks),
        "__SMARTPHONE_SOURCE_CONDITION__": condition(smartphone_networks),
        "__TRUSTED_SOURCE_CONDITION__": condition(
            asterisk_networks + carrier_networks + smartphone_networks
        ),
    }
    rendered = TEMPLATE.read_text(encoding="utf-8")
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    if "__" in rendered:
        raise ValueError("unresolved Kamailio template marker")
    OUTPUT.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()

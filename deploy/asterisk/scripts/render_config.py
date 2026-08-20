from __future__ import annotations

import os
import re
from ipaddress import ip_address, ip_network
from pathlib import Path


TEMPLATE_DIR = Path("/opt/anshin-phone/templates")
CONFIG_DIR = Path("/etc/asterisk")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required runtime value is missing: {name}")
    if "\n" in value or "\r" in value:
        raise RuntimeError(f"runtime value contains a newline: {name}")
    return value


def secret(name: str) -> str:
    path = Path(required(f"{name}_FILE"))
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"secret is empty: {name}")
    if "\n" in value or "\r" in value:
        raise RuntimeError(f"secret contains a newline: {name}")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def digits(name: str, minimum: int, maximum: int) -> str:
    value = required(name)
    if not value.isdigit() or not minimum <= len(value) <= maximum:
        raise RuntimeError(f"{name} must contain {minimum} to {maximum} digits")
    return value


def render(template_name: str, target_name: str, replacements: dict[str, str]) -> None:
    content = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        content = content.replace(f"__{key}__", value)
    unresolved = sorted({part.split("__", 1)[0] for part in content.split("__")[1::2]})
    if unresolved:
        raise RuntimeError(f"unresolved template tokens in {template_name}: {unresolved}")
    target = CONFIG_DIR / target_name
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)


def main() -> None:
    auth_mode = required("CARRIER_AUTH_MODE")
    if auth_mode not in {"registration", "ip"}:
        raise RuntimeError("CARRIER_AUTH_MODE must be registration or ip")

    carrier_host = required("CARRIER_HOST")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", carrier_host):
        raise RuntimeError("CARRIER_HOST must be an IPv4 address or DNS hostname")
    carrier_port = required("CARRIER_PORT")
    if not carrier_port.isdigit() or not 1 <= int(carrier_port) <= 65535:
        raise RuntimeError("CARRIER_PORT must be between 1 and 65535")

    source_cidrs = [item.strip() for item in required("CARRIER_SOURCE_CIDRS").split(",") if item.strip()]
    if not source_cidrs:
        raise RuntimeError("CARRIER_SOURCE_CIDRS must not be empty")
    for cidr in source_cidrs:
        ip_network(cidr, strict=False)
    identify = ["[carrier-identify]", "type=identify", "endpoint=carrier-endpoint"]
    identify.extend(f"match={cidr}" for cidr in source_cidrs)

    username = required("CARRIER_SIP_USERNAME")
    if not re.fullmatch(r"[A-Za-z0-9_.+@-]+", username):
        raise RuntimeError("CARRIER_SIP_USERNAME contains unsupported characters")
    tel_did = digits("TEL_DID", 10, 11)
    fax_did = digits("FAX_DID", 10, 11)
    if not tel_did.startswith("0") or not fax_did.startswith("0"):
        raise RuntimeError("TEL_DID and FAX_DID must use the domestic 0-prefixed form")
    smartphone_extension = digits("SMARTPHONE_EXTENSION", 3, 8)
    public_ip = required("PUBLIC_SIP_IP")
    ip_address(public_ip)

    registration = ""
    if auth_mode == "registration":
        registration = "\n".join(
            [
                "[carrier-registration]",
                "type=registration",
                "transport=transport-udp",
                "outbound_auth=carrier-auth",
                f"server_uri=sip:{carrier_host}:{carrier_port}",
                f"client_uri=sip:{username}@{carrier_host}",
                f"contact_user={tel_did}",
                "retry_interval=30",
                "forbidden_retry_interval=300",
                "expiration=300",
            ]
        )

    common = {
        "CARRIER_HOST": carrier_host,
        "CARRIER_PORT": carrier_port,
        "CARRIER_SIP_USERNAME": username,
        "CARRIER_SIP_PASSWORD": secret("CARRIER_SIP_PASSWORD"),
        "PUBLIC_SIP_IP": public_ip,
        "TEL_DID": tel_did,
        "FAX_DID": fax_did,
        "SMARTPHONE_EXTENSION": smartphone_extension,
        "SMARTPHONE_SIP_PASSWORD": secret("SMARTPHONE_SIP_PASSWORD"),
        "CARRIER_IDENTIFY_BLOCK": "\n".join(identify),
        "CARRIER_REGISTRATION_BLOCK": registration,
    }
    render("pjsip.conf.template", "pjsip.conf", common)
    render("extensions.conf.template", "extensions.conf", common)


if __name__ == "__main__":
    main()

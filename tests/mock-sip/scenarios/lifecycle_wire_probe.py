"""Aggregate synthetic SIP/RTP wire metadata; never retain authentication headers."""
import json
from pathlib import Path
import re
import socket
import sys
import time


def main():
    role = sys.argv[1]
    assert role in ("carrier", "device")
    local, peer = (("10.254.250.10", "10.254.250.20") if role == "carrier"
                   else ("10.254.251.30", "10.254.251.20"))
    packets, sip = [], []
    deadline = time.monotonic() + 150
    # ETH_P_ALL includes the local PACKET_OUTGOING tap. ETH_P_IP alone only
    # delivered incoming packets in this fixture and hid caller INVITE/RTP.
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)) as sock:
        sock.settimeout(.2)
        Path(f"/tmp/lifecycle-wire-{role}-ready").touch()
        while time.monotonic() < deadline:
            if Path("/tmp/lifecycle-wire-stop").exists():
                break
            try:
                frame = sock.recv(65535)
            except socket.timeout:
                continue
            if len(frame) < 42 or frame[12:14] != b"\x08\x00":
                continue
            ip = frame[14:]
            size = (ip[0] & 15) * 4
            if ip[9] != 17:
                continue
            source, target = socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20])
            if {source, target} != {local, peer}:
                continue
            udp = ip[size:]
            sport, dport = int.from_bytes(udp[:2], "big"), int.from_bytes(udp[2:4], "big")
            payload = udp[8:]
            value = {"at": time.monotonic(), "source": source, "sport": sport,
                     "target": target, "dport": dport}
            if 5060 in (sport, dport):
                message = payload.decode(errors="replace")
                first, _, body = message.partition("\r\n\r\n")
                headers = dict((key.lower(), field.strip()) for key, field in
                               re.findall(r"^([^:\r\n]+):\s*([^\r\n]*)", first, re.M))
                value.update(first=first.split("\r\n")[0],
                             call_id=headers.get("call-id"), cseq=headers.get("cseq"),
                             from_tag=re.search(r";tag=([^; >]+)", headers.get("from", ""))[1]
                             if ";tag=" in headers.get("from", "") else None,
                             to_tag=re.search(r";tag=([^; >]+)", headers.get("to", ""))[1]
                             if ";tag=" in headers.get("to", "") else None,
                             sdp=body if headers.get("content-type") == "application/sdp" else "")
                sip.append(value)
            elif len(payload) >= 12 and payload[0] >> 6 == 2 and payload[1] & 127 == 0:
                value.update(sequence=int.from_bytes(payload[2:4], "big"),
                             ssrc=int.from_bytes(payload[8:12], "big"), octets=len(payload) - 12)
                packets.append(value)
    Path(f"/tmp/lifecycle-wire-{role}.json").write_text(json.dumps({"sip": sip, "rtp": packets}))
    print(f"phase=lifecycle-wire role={role} sip={len(sip)} rtp={len(packets)}", flush=True)


if __name__ == "__main__":
    main()

"""Synthetic Digest registrar for the existing isolated carrier fixture only."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import re
import socket
import time


def md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persistent", action="store_true")
    persistent = parser.parse_args().persistent
    events = []
    realm, nonce = "phone-isolated-test", "fixed-isolated-registration-nonce"
    authenticated = False
    deadline = time.monotonic() + (180 if persistent else 60)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(("10.254.250.10", 5060))
        server.settimeout(1)
        Path("/tmp/registration-probe-ready").touch()
        while time.monotonic() < deadline:
            if persistent and Path("/tmp/registration-probe-stop").exists():
                print("PASS: persistent synthetic registrar stopped", flush=True)
                return
            try:
                data, source = server.recvfrom(16384)
            except socket.timeout:
                continue
            first, *lines = data.decode().split("\r\n")
            if not first.startswith("REGISTER "):
                continue
            assert source == ("10.254.250.20", 5060), "REGISTER must come directly from PBX"
            headers = {}
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.lower()] = value.strip()
            auth = headers.get("authorization", "")
            status = "401 Unauthorized"
            extra = f'WWW-Authenticate: Digest realm="{realm}", nonce="{nonce}", algorithm=MD5, qop="auth"\r\n'
            if auth:
                values = {key: quoted or bare for key, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^, ]+))', auth)}
                assert values["username"] == "mock-carrier" and values["realm"] == realm
                assert values["nonce"] == nonce and values["qop"] == "auth"
                assert values["uri"] == first.split()[1]
                ha1 = md5(f"mock-carrier:{realm}:test-carrier-password")
                ha2 = md5("REGISTER:" + values["uri"])
                expected = md5(":".join([ha1, nonce, values["nc"], values["cnonce"], "auth", ha2]))
                assert hmac.compare_digest(values["response"], expected), "invalid synthetic Digest"
                contact = re.search(r"<sip:([^@;>]+)@([0-9.]+):([0-9]+)(?:;[^>]*)?>", headers["contact"])
                assert contact and contact[1] == "0300000001", "REGISTER Contact identity mismatch"
                assert (contact[2], int(contact[3])) == source, "REGISTER Contact must advertise the PBX carrier socket"
                expires = int(headers.get("expires", "300"))
                per_contact = re.search(r";expires=([0-9]+)", headers["contact"])
                if per_contact: expires = int(per_contact[1])
                event = {"call_id": headers["call-id"], "cseq": headers["cseq"],
                         "expires": expires, "at": time.monotonic()}
                # Retransmitted requests do not count as a new binding.
                if not events or (events[-1]["call_id"], events[-1]["cseq"]) != (event["call_id"], event["cseq"]):
                    events.append(event)
                value = {"user": contact[1], "host": contact[2], "port": int(contact[3])}
                if persistent:
                    value.update(active=expires > 0, events=events)
                temporary = Path("/tmp/registered-contact.tmp")
                temporary.write_text(json.dumps(value))
                temporary.replace("/tmp/registered-contact.json")
                authenticated = True
                status = "200 OK"
                extra = "Contact: " + headers["contact"] + "\r\nExpires: " + headers.get("expires", "300") + "\r\n"
            to = headers["to"]
            if ";tag=" not in to:
                to += ";tag=isolated-registrar"
            reply = (f"SIP/2.0 {status}\r\nVia: {headers['via']}\r\nFrom: {headers['from']}\r\n"
                     f"To: {to}\r\nCall-ID: {headers['call-id']}\r\nCSeq: {headers['cseq']}\r\n"
                     + extra + "Content-Length: 0\r\n\r\n")
            server.sendto(reply.encode(), source)
            if authenticated and status == "200 OK":
                Path("/tmp/registration-probe-passed").touch()
                if not persistent and (headers.get("expires") == "0" or ";expires=0" in headers.get("contact", "")):
                    print("PASS: direct PBX REGISTER, real Digest challenge, Contact and unregister", flush=True)
                    return
    raise RuntimeError("synthetic registration did not complete")


if __name__ == "__main__":
    main()

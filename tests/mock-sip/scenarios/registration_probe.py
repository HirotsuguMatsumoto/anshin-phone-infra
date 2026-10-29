"""Synthetic Digest registrar for the existing isolated carrier fixture only."""
import hashlib
import hmac
from pathlib import Path
import re
import socket
import time


def md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def main():
    realm, nonce = "phone-isolated-test", "fixed-isolated-registration-nonce"
    authenticated = False
    deadline = time.monotonic() + 60
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(("10.254.250.10", 5060))
        server.settimeout(1)
        Path("/tmp/registration-probe-ready").touch()
        while time.monotonic() < deadline:
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
                if headers.get("expires") == "0" or ";expires=0" in headers.get("contact", ""):
                    print("PASS: direct PBX REGISTER, real Digest challenge, Contact and unregister", flush=True)
                    return
    raise RuntimeError("synthetic registration did not complete")


if __name__ == "__main__":
    main()

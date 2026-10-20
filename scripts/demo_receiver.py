import hashlib
import hmac
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9000
HOOK_PATH = "/hook"
TOLERANCE_SECONDS = 300


def verify_signature(secret: str, header: str, body: bytes, now: float) -> bool:
    values = {}
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        values[name] = value
    timestamp = values.get("t", "")
    signature = values.get("v1", "")
    if not secret or not timestamp.isdecimal() or not signature:
        return False
    if abs(now - int(timestamp)) > TOLERANCE_SECONDS:
        return False
    message = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


class HookHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != HOOK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        event_id = self.headers.get("Hookline-Event-Id", "unknown")
        header = self.headers.get("Hookline-Signature", "")
        secret = os.environ.get("RECEIVER_SECRET", "")
        if not verify_signature(secret, header, body, time.time()):
            print(f"Rejected event {event_id}: invalid signature", flush=True)
            self.send_response(401)
            self.end_headers()
            return
        print(f"Verified signature for event {event_id}", flush=True)
        self.send_response(204)
        self.end_headers()


def main() -> None:
    server = HTTPServer(("0.0.0.0", PORT), HookHandler)
    print(f"Demo receiver listening on port {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

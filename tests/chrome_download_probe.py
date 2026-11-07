"""P2-M1 Chrome feasibility harness (manual; launches a visible Chrome window for ~40 s).

    python -I tests/chrome_download_probe.py <empty scratch folder>
    python -m late_night_workshop.downloads --user-data <scratch>/chrome-profile   (run from src/)

Uses a disposable profile (never the user's), a localhost server and two sanitized files:
lnp-probe-complete.txt finishes in <scratch>/custom-save-location (not Downloads);
lnp-probe-incomplete.txt is cancelled mid-transfer through DevTools Browser.cancelDownload.
Chrome is closed before the provider reads History, so the completed download predates the probe.
The profile disables Safe Browsing and allows automatic downloads only so the localhost
test files are not held as "Unconfirmed" by Chrome's checks.
"""

import base64
import http.server
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333
DEVTOOLS = f"http://127.0.0.1:{PORT}"


class Server(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        slow = self.path.startswith("/slow")
        body = b"Late Night Pal download probe\n" * 100
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        name = "lnp-probe-incomplete.txt" if slow else "lnp-probe-complete.txt"
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(50_000_000 if slow else len(body)))
        self.end_headers()
        try:
            if not slow:
                self.wfile.write(body)
                return
            for _ in range(300):  # 1 KB / 0.2 s of a declared 50 MB: still running when cancelled
                self.wfile.write(b"x" * 1024)
                self.wfile.flush()
                time.sleep(0.2)
        except OSError:
            pass


class CDP:
    """Just enough of a WebSocket client for two DevTools commands (stdlib only)."""

    def __init__(self, ws_url):
        host, rest = ws_url[len("ws://"):].split("/", 1)
        h, port = host.split(":")
        self.s = socket.create_connection((h, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall("\r\n".join([f"GET /{rest} HTTP/1.1", f"Host: {host}", "Upgrade: websocket",
                                    "Connection: Upgrade", f"Sec-WebSocket-Key: {key}",
                                    "Sec-WebSocket-Version: 13", "", ""]).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(1)
        self.n = 0

    def send(self, method, **params):
        self.n += 1
        data = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        size = bytes([0x80 | len(data)]) if len(data) < 126 else bytes([0xFE]) + struct.pack(">H", len(data))
        mask = os.urandom(4)
        self.s.sendall(bytes([0x81]) + size + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _exact(self, n):
        b = b""
        while len(b) < n:
            b += self.s.recv(n - len(b))
        return b

    def recv(self):
        _, b1 = self._exact(2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._exact(8))[0]
        return json.loads(self._exact(n))


def wait_for(cond, secs):
    for _ in range(secs * 4):
        if cond():
            return True
        time.sleep(0.25)
    return False


def main(base: Path) -> None:
    profile, custom = base / "chrome-profile", base / "custom-save-location"
    custom.mkdir(parents=True, exist_ok=True)
    (profile / "Default").mkdir(parents=True, exist_ok=True)
    (profile / "Default" / "Preferences").write_text(json.dumps({
        "download": {"default_directory": str(custom), "prompt_for_download": False, "directory_upgrade": True},
        "profile": {"exit_type": "Normal", "default_content_setting_values": {"automatic_downloads": 1}},
        "safebrowsing": {"enabled": False}}))
    servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server) for _ in range(2)]  # two origins
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    first, second = (f"http://127.0.0.1:{s.server_port}" for s in servers)

    chrome = subprocess.Popen([CHROME, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                               "--disable-sync", f"--remote-debugging-port={PORT}", first + "/complete"])
    print("complete saved:", wait_for((custom / "lnp-probe-complete.txt").is_file, 30))
    time.sleep(2)
    cdp = CDP(json.load(urllib.request.urlopen(DEVTOOLS + "/json/version"))["webSocketDebuggerUrl"])
    cdp.send("Browser.setDownloadBehavior", behavior="default", eventsEnabled=True)
    urllib.request.urlopen(urllib.request.Request(
        DEVTOOLS + "/json/new?" + urllib.parse.quote(second + "/slow", safe=":/"), method="PUT"))
    guid = None
    while guid is None:
        m = cdp.recv()
        if m.get("method") == "Browser.downloadWillBegin":
            guid = m["params"]["guid"]
    time.sleep(6)
    print("before cancel:", sorted(p.name for p in custom.iterdir()))
    cdp.send("Browser.cancelDownload", guid=guid)
    time.sleep(15)  # History commits on a timer
    print("after cancel:", sorted(p.name for p in custom.iterdir()))
    for t in json.load(urllib.request.urlopen(DEVTOOLS + "/json/list")):
        if t.get("type") == "page":
            urllib.request.urlopen(urllib.request.Request(f"{DEVTOOLS}/json/close/{t['id']}", method="PUT"))
    print("chrome closed normally:", wait_for(lambda: chrome.poll() is not None, 20))
    if chrome.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(chrome.pid)], capture_output=True)
    for s in servers:
        s.shutdown()
    print("profile:", profile)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())

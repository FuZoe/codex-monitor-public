import argparse
import json
import os
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_NAME = "codex-monitor"
VERSION = "1.0"
DISCOVERY_MESSAGE = b"CODEX_MONITOR_DISCOVER_V1"


class MonitorState:
    def __init__(self, root: Path):
        self.root = root
        self.status_path = root / "codex-status.json"

    def read(self):
        if self.status_path.exists():
            with self.status_path.open("r", encoding="utf-8-sig") as handle:
                return json.load(handle)
        return {
            "status": "working",
            "title": "Working",
            "task": "Codex is working",
            "turn": "Current thread",
            "quotas": [
                {
                    "id": "five_hour",
                    "label": "5-hour limit",
                    "used": 0,
                    "limit": 100,
                    "unit": "messages",
                    "resetAt": "",
                },
                {
                    "id": "weekly",
                    "label": "Weekly limit",
                    "used": 0,
                    "limit": 500,
                    "unit": "messages",
                    "resetAt": "",
                },
            ],
        }


def local_ipv4_addresses():
    addresses = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addresses and not ip.startswith("127."):
                addresses.append(ip)
    except OSError:
        pass

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        if ip not in addresses and not ip.startswith("127."):
            addresses.append(ip)
    except OSError:
        pass
    finally:
        probe.close()
    return addresses


def make_handler(root: Path, state: MonitorState, http_port: int):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "CodexMonitor/1.0"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/ping":
                self.send_json({
                    "app": APP_NAME,
                    "version": VERSION,
                    "httpPort": http_port,
                    "statusPath": "/api/status",
                })
                return
            if path == "/api/status":
                self.send_json(state.read())
                return
            if path == "/":
                self.path = "/codex-monitor.html"
            return super().do_GET()

        def send_json(self, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            print("%s - %s" % (self.client_address[0], format % args))

    return Handler


def discovery_loop(http_port: int, discovery_port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", discovery_port))
    print(f"Discovery listening on UDP {discovery_port}")
    while True:
        try:
            data, address = sock.recvfrom(2048)
            if data.strip() != DISCOVERY_MESSAGE:
                continue
            payload = json.dumps({
                "app": APP_NAME,
                "version": VERSION,
                "httpPort": http_port,
                "statusPath": "/api/status",
            }).encode("utf-8")
            sock.sendto(payload, address)
        except OSError as exc:
            print(f"Discovery error: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Codex monitor desktop server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--discovery-port", type=int, default=45777)
    parser.add_argument("--root", default=os.path.dirname(__file__))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    state = MonitorState(root)
    handler = make_handler(root, state, args.port)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    thread = threading.Thread(
        target=discovery_loop,
        args=(args.port, args.discovery_port),
        daemon=True,
    )
    thread.start()

    print("Codex Monitor server is running")
    print(f"Local: http://127.0.0.1:{args.port}/")
    for ip in local_ipv4_addresses():
        print(f"LAN:   http://{ip}:{args.port}/")
    print("Android app will discover this server automatically on the same Wi-Fi.")
    server.serve_forever()


if __name__ == "__main__":
    main()

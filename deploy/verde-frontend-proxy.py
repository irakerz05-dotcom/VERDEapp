#!/usr/bin/env python3
"""Serve the VERDE PWA and proxy backend API/camera requests."""

import argparse
import json
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class VerdeHandler(SimpleHTTPRequestHandler):
    backend_url = "http://127.0.0.1:8001"

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.proxy_request()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.proxy_request()
        else:
            self.send_error(405)

    def proxy_request(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        request = urllib.request.Request(
            f"{self.backend_url}{self.path}",
            data=body,
            method=self.command,
            headers={key: value for key, value in self.headers.items()
                     if key.lower() in {"content-type", "x-verde-token"}},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"connection", "transfer-encoding", "server", "date"}:
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as error:
            payload = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            payload = json.dumps({"error": f"VERDE backend unavailable: {error}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    VerdeHandler.backend_url = args.backend.rstrip("/")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), VerdeHandler)
    print(f"VERDE frontend on port {args.port}; API proxy to {VerdeHandler.backend_url}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

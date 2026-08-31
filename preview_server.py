#!/usr/bin/env python3
"""Dev server for preview.html — serves static files + proxies /bin/ to binlist.net"""
import http.server
import urllib.request
import json
import os

PORT = 9090
ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path.startswith("/bin/"):
            self._proxy_bin()
        else:
            super().do_GET()

    def _proxy_bin(self):
        bin_digits = self.path[5:].split("?")[0]
        if not bin_digits.isdigit() or len(bin_digits) < 6:
            self._json({})
            return
        try:
            req = urllib.request.Request(
                f"https://lookup.binlist.net/{bin_digits[:8]}",
                headers={"Accept-Version": "3", "User-Agent": "preview-dev/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
            self._json(data)
        except Exception as e:
            print(f"BIN lookup error: {e}")
            self._json({})

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    with http.server.HTTPServer(("", PORT), Handler) as srv:
        print(f"Preview server: http://localhost:{PORT}/preview.html")
        srv.serve_forever()

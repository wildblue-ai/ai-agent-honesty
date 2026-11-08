#!/usr/bin/env python3
"""Serve the dashboard over http on 127.0.0.1:7577, so the Inspect viewer (http) can link to it.

    .venv/bin/python scripts/serve_dashboard.py        # then open http://127.0.0.1:7577/dashboard/index.html

Serves this experiment folder, read-only, on the loopback address only. It refuses any path with a part starting with
"." (the key file, .git, .venv) and anything outside the folder. Standard library only.
"""
from __future__ import annotations

import http.server
import posixpath
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 7577


class SafeHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _blocked(self) -> bool:
        path = posixpath.normpath(urllib.parse.unquote(urllib.parse.urlsplit(self.path).path))
        parts = [p for p in path.split("/") if p]
        if any(p.startswith(".") for p in parts):
            return True
        target = (ROOT / Path(*parts)).resolve() if parts else ROOT
        return ROOT not in target.parents and target != ROOT

    def do_GET(self):
        if self._blocked():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if self._blocked():
            self.send_error(404)
            return
        super().do_HEAD()

    def list_directory(self, path):
        # Hide dot entries in directory listings too.
        self.send_error(404) if Path(path).name.startswith(".") else None
        return super().list_directory(path)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), SafeHandler) as httpd:
        print(f"Dashboard: http://127.0.0.1:{PORT}/dashboard/index.html", flush=True)
        httpd.serve_forever()

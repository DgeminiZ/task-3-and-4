"""Минимальный статический сервер для локального режима (без Docker).

Повторяет поведение nginx-конфигурации из sut/: корректные MIME-типы и
no-cache для service worker, чтобы PWA обновлялась предсказуемо.
"""

from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".webmanifest": "application/manifest+json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".json": "application/json; charset=utf-8",
    }

    def end_headers(self) -> None:  # noqa: D401
        if self.path.split("?")[0] in {"/sw.js", "/manifest.webmanifest"}:
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    root = str(Path(args.root).resolve())
    handler = functools.partial(Handler, directory=root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving {root} on http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

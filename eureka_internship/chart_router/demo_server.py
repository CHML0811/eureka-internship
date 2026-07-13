"""Stdlib-only local HTTP boundary for the chart router demo UI."""

from __future__ import annotations

import argparse
import asyncio
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from chart_router.router import ChartRouter

UI_PATH = Path(__file__).with_name("demo_ui") / "index.html"
MAX_REQUEST_BYTES = 1_000_000
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'unsafe-inline'; connect-src 'self'; img-src data:"
    ),
}


async def route_payload(
    payload: dict[str, Any],
    *,
    router: ChartRouter | None = None,
) -> dict[str, Any]:
    """Validate a JSON request and return a JSON-ready route result."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    data = payload.get("data")
    if data is not None:
        if not isinstance(data, list) or not all(
            isinstance(row, dict) for row in data
        ):
            raise ValueError("data must be null or an array of objects")
    result = await (router or ChartRouter()).route(question, data=data)
    return result.model_dump()


class DemoHandler(BaseHTTPRequestHandler):
    """Serve the UI and its same-origin routing endpoint."""

    server_version = "EurekaChartDemo/1.0"

    def _security_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)

    def _json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = UI_PATH.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/api/route":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                raise ValueError("request body must be between 1 byte and 1 MB")
            payload = json.loads(self.rfile.read(content_length))
            result = asyncio.run(route_payload(payload))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:  # endpoint boundary; never leak a traceback
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"routing failed: {exc}"},
            )
            return
        self._json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[chart-demo] {self.address_string()} {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8008)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"Local chart demo: http://{args.host}:{args.port}")
    print("Python mock routing is local; CDN renderers require network access.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

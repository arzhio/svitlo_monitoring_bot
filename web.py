from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import PING_PATH


class PingRequestHandler(BaseHTTPRequestHandler):
    monitor_service = None

    def do_GET(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path != PING_PATH:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        api_key = parse_qs(parsed_url.query).get("api_key", [None])[0]
        if not api_key:
            self._send_json(HTTPStatus.BAD_REQUEST, '{"ok": false, "message": "api_key is required"}')
            return

        ok, message = self.monitor_service.handle_ping(api_key=api_key)
        if not ok:
            self._send_json(HTTPStatus.NOT_FOUND, '{"ok": false, "message": "invalid api_key"}')
            return

        self._send_json(HTTPStatus.OK, f'{{"ok": true, "message": "{message}"}}')

    def log_message(self, format, *args):
        return

    def _send_json(self, status_code: HTTPStatus, payload: str) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))


class PingServer:
    def __init__(self, host: str, port: int, monitor_service):
        PingRequestHandler.monitor_service = monitor_service
        self.server = ThreadingHTTPServer((host, port), PingRequestHandler)

    def serve_forever(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()

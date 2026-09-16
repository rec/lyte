"""Loopback operator panel for the existing lyte installation service."""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal

from pydantic import BaseModel, Field
from reccy.protocol import rpc

from .installation import InstallationService, InstallationStatus
from .panel_template import PANEL_TEMPLATE


class PanelConfig(BaseModel, frozen=True):
    port: int = Field(default=8767, ge=1024, le=65535)
    open: bool = True


class PanelCommand(BaseModel, frozen=True):
    command: Literal['select_animation', 'test', 'blackout', 'stop', 'master_level']
    params: dict[str, object] = Field(default_factory=dict)


def run_panel(config: PanelConfig) -> int:
    endpoint = InstallationService.model_construct().control_endpoint
    client = rpc.Client(endpoint, role='lyte-panel', timeout=1)
    server = HTTPServer(('127.0.0.1', config.port), handler(client))
    if config.open:
        webbrowser.open(f'http://127.0.0.1:{config.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def handler(client: rpc.Client) -> type[BaseHTTPRequestHandler]:
    class PanelHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == '/':
                self.respond(200, PANEL_TEMPLATE.encode(), 'text/html; charset=utf-8')
                return
            if self.path != '/api/status':
                self.send_error(404)
                return
            try:
                status = InstallationStatus.model_validate(client.call('status'))
                self.respond(200, status.model_dump_json().encode())
            except (OSError, ValueError) as error:
                self.respond(503, json.dumps({'error': str(error)}).encode())

        def do_POST(self) -> None:
            if self.path != '/api/command':
                self.send_error(404)
                return
            if self.headers.get_content_type() != 'application/json':
                self.send_error(415, 'commands require application/json')
                return
            assert isinstance(self.server, HTTPServer)
            allowed_hosts = {
                f'127.0.0.1:{self.server.server_port}',
                f'localhost:{self.server.server_port}',
            }
            if self.headers.get('Host') not in allowed_hosts or (
                self.headers.get('Origin') is not None
                and self.headers.get('Origin')
                not in {f'http://{h}' for h in allowed_hosts}
            ):
                self.send_error(403, 'commands require the local panel origin')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('request must be between 1 and 65536 bytes')
                request = PanelCommand.model_validate_json(self.rfile.read(length))
                result = client.call(request.command, **request.params)
                self.respond(200, json.dumps({'result': result}).encode())
            except (OSError, ValueError) as error:
                self.respond(400, json.dumps({'error': str(error)}).encode())

        def respond(
            self, status: int, data: bytes, content_type: str = 'application/json'
        ) -> None:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    return PanelHandler

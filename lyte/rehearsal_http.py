"""Local browser interface for software-only installation rehearsal."""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from .rehearsal import RehearsalConfig, RehearsalRequest, RehearsalSession
from .rehearsal_template import REHEARSAL_TEMPLATE


def run_rehearsal(config: RehearsalConfig) -> int:
    session = RehearsalSession(config)
    try:
        with HTTPServer(('127.0.0.1', config.port), handler(session)) as server:
            if config.open:
                webbrowser.open(f'http://127.0.0.1:{config.port}')
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
    return 0


def handler(session: RehearsalSession) -> type[BaseHTTPRequestHandler]:
    class RehearsalHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != '/':
                self.send_error(404)
                return
            data = REHEARSAL_TEMPLATE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            if self.path != '/api/rehearse':
                self.send_error(404)
                return
            status = 200
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('request must be between 1 and 65536 bytes')
                request = RehearsalRequest.model_validate_json(self.rfile.read(length))
                result = session.request(request)
            except (ValueError, TypeError, KeyError, OSError) as error:
                status = 400
                result = {'error': str(error)}
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    return RehearsalHandler

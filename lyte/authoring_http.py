"""Loopback HTTP interface for the animation editor."""

from __future__ import annotations

import json
import webbrowser
from difflib import unified_diff
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import cast
from urllib.parse import urlparse

from ufor import library_files

from . import authoring, show


def run_author(config: authoring.AuthorConfig) -> int:
    library = library_files.read_library(config.library_config)
    show.log_diagnostics(library)
    session = authoring.AuthoringSession(library, config)
    if not session.animations:
        raise ValueError('selected library contains no animation scores')
    server = ThreadingHTTPServer(('127.0.0.1', config.port), _handler(session))
    if config.open:
        webbrowser.open(f'http://127.0.0.1:{config.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _handler(session: authoring.AuthoringSession) -> type[BaseHTTPRequestHandler]:
    session_lock = Lock()

    class AuthorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlparse(self.path).path != '/':
                self.send_error(404)
                return
            document = authoring.author_document(
                session.animations, session.history_state()
            ).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(document)))
            self.end_headers()
            self.wfile.write(document)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {
                '/api/preview',
                '/api/thumbnail',
                '/api/preset',
                '/api/operation',
                '/api/timeline',
                '/api/fields',
                '/api/structure',
                '/api/undo',
                '/api/redo',
                '/api/bundle',
            }:
                self.send_error(404)
                return
            if not session_lock.acquire(blocking=False):
                self._json(
                    429,
                    {
                        'error': (
                            'Another editor request is running; '
                            'try again when it finishes.'
                        )
                    },
                )
                return
            try:
                payload = _request_json(self)
                response: dict[str, object]
                if path == '/api/bundle':
                    response = session.download_bundle()
                elif path in {'/api/undo', '/api/redo'}:
                    if path == '/api/undo':
                        session.undo()
                    else:
                        session.redo()
                    response = {}
                elif path in {
                    '/api/operation',
                    '/api/timeline',
                    '/api/fields',
                    '/api/structure',
                }:
                    entry = payload.get('entry')
                    output = payload.get('output')
                    if not isinstance(entry, str) or not isinstance(output, str):
                        raise ValueError('timing requires entry and output')
                    assert isinstance(entry, str)
                    assert isinstance(output, str)
                    if path == '/api/structure':
                        structure = payload.get('structure')
                        apply = payload.get('apply')
                        if not isinstance(structure, dict) or not isinstance(
                            apply, bool
                        ):
                            raise ValueError(
                                'structure requires a draft and apply flag'
                            )
                        original = session.library.entries.get(entry)
                        if original is None:
                            raise ValueError('unknown score')
                        before = session.documents.get(entry)
                        if before is None:
                            before = session.source_document(entry)
                        text = session.structure_document(
                            entry, output, structure, apply=apply
                        )
                        response = {
                            'filename': Path(entry).name,
                            'document': text,
                            'diff': ''.join(
                                unified_diff(
                                    before.splitlines(keepends=True),
                                    text.splitlines(keepends=True),
                                    fromfile='working score',
                                    tofile='proposed score',
                                )
                            ),
                        }
                    elif path == '/api/operation':
                        template = payload.get('template')
                        if not isinstance(template, str):
                            raise ValueError('operation requires a template')
                        response = {
                            'filename': Path(entry).name,
                            'document': session.operation_document(
                                entry, output, template
                            ),
                        }
                    elif path == '/api/timeline':
                        timing = payload.get('timing')
                        if not isinstance(timing, dict):
                            raise ValueError('timing requires timing values')
                        response = {
                            'filename': Path(entry).name,
                            'document': session.timeline_document(
                                entry, output, timing
                            ),
                        }
                    else:
                        fields = payload.get('fields')
                        if not isinstance(fields, dict):
                            raise ValueError('fields requires operation values')
                        response = {
                            'filename': Path(entry).name,
                            'document': session.field_document(entry, output, fields),
                        }
                else:
                    selector, parameters = _preview_request(payload)
                    if path == '/api/thumbnail':
                        response = session.thumbnail(selector)
                    elif path == '/api/preview':
                        response = session.preview(selector, parameters)
                    else:
                        name = payload.get('name')
                        if not isinstance(name, str):
                            raise ValueError('preset requires a name')
                        response = {
                            'filename': f'{name}.toml',
                            'document': session.preset_document(
                                selector, parameters, name
                            ),
                        }
                if path in {'/api/operation', '/api/timeline', '/api/fields'} or (
                    path == '/api/structure' and payload.get('apply') is True
                ):
                    response['revisions'] = {
                        entry: authoring.document_revision(session.documents[entry])
                    }
                if path not in {'/api/preview', '/api/preset', '/api/thumbnail'}:
                    response['catalog'] = [a.document() for a in session.animations]
                    response['history'] = session.history_state()
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {'error': str(error)})
                return
            finally:
                session_lock.release()
            self._json(200, response)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: int, value: dict[str, object]) -> None:
            document = json.dumps(value, separators=(',', ':')).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(document)))
            self.end_headers()
            self.wfile.write(document)

    return AuthorHandler


def _request_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get('Content-Length', '0'))
    if not 0 < length <= 64 * 1024:
        raise ValueError('preview request body must be between 1 and 65536 bytes')
    data = json.loads(handler.rfile.read(length))
    if not isinstance(data, dict):
        raise ValueError('preview request must be a JSON object')
    return data


def _preview_request(payload: dict[str, object]) -> tuple[str, dict[str, float]]:
    selector = payload.get('selector')
    parameters = payload.get('parameters', {})
    if not isinstance(selector, str):
        raise ValueError('preview requires a selector')
    if not isinstance(parameters, dict) or any(
        not isinstance(name, str)
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        for name, value in parameters.items()
    ):
        raise ValueError('preview parameters must map names to numbers')
    return selector, cast(dict[str, float], parameters)

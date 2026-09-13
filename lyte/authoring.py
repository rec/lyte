"""Loopback browser editor for declared Ufor animation parameters."""

# ruff: noqa: E501

from __future__ import annotations

import json
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from ufor import library_files
from ufor.library import Library
from ufor.light_animation import AnimationScore

from . import show
from .preview.document import encoded_frames


class AuthorConfig(BaseModel, frozen=True):
    library_config: Path | None = None
    light_output: str = 'light'
    duration: float = Field(default=10, gt=0)
    port: int = Field(default=8765, ge=1024, le=65535)
    open: bool = True


@dataclass(frozen=True)
class AuthorParameter:
    name: str
    minimum: float
    maximum: float
    default: float
    unit: str

    def document(self) -> dict[str, object]:
        return {
            'name': self.name,
            'minimum': self.minimum,
            'maximum': self.maximum,
            'default': self.default,
            'unit': self.unit,
        }


@dataclass(frozen=True)
class AuthorAnimation:
    selector: str
    title: str
    parameters: list[AuthorParameter]

    def document(self) -> dict[str, object]:
        return {
            'selector': self.selector,
            'title': self.title,
            'parameters': [parameter.document() for parameter in self.parameters],
        }


class AuthoringSession:
    def __init__(self, library: Library, config: AuthorConfig) -> None:
        self.library = library
        self.config = config
        self.animations = _author_animations(library)

    def preview(self, selector: str, parameters: dict[str, float]) -> dict[str, object]:
        if selector not in {animation.selector for animation in self.animations}:
            raise ValueError(f'unknown animation {selector!r}')
        prepared = show.prepare_library_animation(
            self.library,
            show.LightProgramSpec(
                selector=selector,
                output=self.config.light_output,
                parameters=parameters,
            ),
        )
        if prepared.output.components != ['red', 'green', 'blue']:
            raise ValueError('authoring preview requires red, green, blue components')
        points = [
            [*light.position, *([0.0] * (2 - len(light.position)))]
            for light in prepared.output.layout.lights
        ]
        return {
            'coords': [point[:2] for point in points],
            'fps': prepared.fps,
            'frames': encoded_frames(prepared, self.config.duration),
        }


def run_author(config: AuthorConfig) -> int:
    library = library_files.read_library(config.library_config)
    show.log_diagnostics(library)
    session = AuthoringSession(library, config)
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


def author_document(animations: list[AuthorAnimation]) -> str:
    if not animations:
        raise ValueError('authoring document requires at least one animation')
    catalog = json.dumps([animation.document() for animation in animations])
    return _AUTHOR_TEMPLATE.replace('__LYTE_AUTHOR_CATALOG__', catalog)


def _author_animations(library: Library) -> list[AuthorAnimation]:
    animations = []
    for entry in library.find():
        if not isinstance(entry.resolved, AnimationScore):
            continue
        selector = entry.name or entry.key
        composition = library.composition(selector)
        parameters = [
            AuthorParameter(
                name=export.name,
                minimum=contract.minimum,
                maximum=contract.maximum,
                default=contract.default,
                unit=contract.unit,
            )
            for export in entry.resolved.parameters
            for contract in [
                composition.parameter_contract(composition.root, export.name)
            ]
        ]
        animations.append(
            AuthorAnimation(
                selector=selector,
                title=entry.resolved.title or selector,
                parameters=parameters,
            )
        )
    return animations


def _handler(session: AuthoringSession) -> type[BaseHTTPRequestHandler]:
    class AuthorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlparse(self.path).path != '/':
                self.send_error(404)
                return
            document = author_document(session.animations).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(document)))
            self.end_headers()
            self.wfile.write(document)

        def do_POST(self) -> None:
            if urlparse(self.path).path != '/api/preview':
                self.send_error(404)
                return
            try:
                payload = _request_json(self)
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
                preview = session.preview(
                    selector,
                    cast(dict[str, float], parameters),
                )
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {'error': str(error)})
                return
            self._json(200, preview)

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


_AUTHOR_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lyte Author</title>
<style>
html,body{height:100%;margin:0;background:#111417;color:#e5e7eb;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{height:100%;display:grid;grid-template-columns:minmax(230px,320px) 1fr}
aside{border-right:1px solid #343a40;padding:16px;overflow:auto}canvas{width:100%;height:100%;display:block}
h1{font-size:17px;margin:0 0 16px}label{display:grid;gap:6px;margin:14px 0;color:#cbd5e1}
select,input{width:100%;box-sizing:border-box}output{font-variant-numeric:tabular-nums;color:#94a3b8}
@media(max-width:700px){main{grid-template-columns:1fr;grid-template-rows:auto 1fr}aside{border-right:0;border-bottom:1px solid #343a40}}
</style>
</head>
<body>
<main><aside><h1>Lyte Author</h1><label>Animation<select id="animation"></select></label><section id="controls"></section></aside><canvas id="preview"></canvas></main>
<script>
const catalog=__LYTE_AUTHOR_CATALOG__;
const select=document.getElementById('animation');
const controls=document.getElementById('controls');
const canvas=document.getElementById('preview');
const context=canvas.getContext('2d');
let preview=null;
for(const animation of catalog){const option=document.createElement('option');option.value=animation.selector;option.textContent=animation.title;select.append(option)}
function active(){return catalog.find(animation=>animation.selector===select.value)}
function values(){return Object.fromEntries([...controls.querySelectorAll('input')].map(input=>[input.name,Number(input.value)]))}
function control(parameter){const label=document.createElement('label');label.textContent=parameter.name;const input=document.createElement('input');input.type='range';input.name=parameter.name;input.min=parameter.minimum;input.max=parameter.maximum;input.step=(parameter.maximum-parameter.minimum)/200||1;input.value=parameter.default;const output=document.createElement('output');output.textContent=`${parameter.default} ${parameter.unit}`;input.oninput=()=>{output.textContent=`${input.value} ${parameter.unit}`;requestPreview()};label.append(input,output);controls.append(label)}
function rebuild(){controls.replaceChildren();for(const parameter of active().parameters){control(parameter)}requestPreview()}
async function requestPreview(){const response=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selector:select.value,parameters:values()})});if(response.ok){preview=await response.json()}}
function resize(){const scale=devicePixelRatio||1;const rect=canvas.getBoundingClientRect();canvas.width=Math.max(1,Math.round(rect.width*scale));canvas.height=Math.max(1,Math.round(rect.height*scale))}
function draw(time){if(preview){const frame=atob(preview.frames[Math.floor(time/1000*preview.fps)%preview.frames.length]);context.fillStyle='#050506';context.fillRect(0,0,canvas.width,canvas.height);for(let index=0;index<preview.coords.length;index+=1){const x=(index+0.5)*canvas.width/preview.coords.length;const offset=index*3;context.fillStyle=`rgb(${frame.charCodeAt(offset)},${frame.charCodeAt(offset+1)},${frame.charCodeAt(offset+2)})`;context.beginPath();context.arc(x,canvas.height/2,Math.max(4,canvas.height/12),0,Math.PI*2);context.fill()}}requestAnimationFrame(draw)}
select.onchange=rebuild;addEventListener('resize',resize);resize();rebuild();requestAnimationFrame(draw);
</script></body></html>"""

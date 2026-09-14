"""Loopback browser editor for declared Ufor animation parameters."""

# ruff: noqa: E501

from __future__ import annotations

import json
import math
import webbrowser
from base64 import b64encode
from dataclasses import dataclass
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

import tomlkit
from pydantic import BaseModel, Field
from tomlkit.items import Table
from ufor import codec, effects, library_files, light_animation
from ufor.base import Model
from ufor.composition import Composition
from ufor.interface import ScoreVersion
from ufor.library import Entry, Library, State
from ufor.light_animation import AnimationScore
from ufor.lights import LightType
from ufor.preset import PresetScore
from ufor.selector import LibraryConfig

from . import animation, reactive_effects, reactivity, show
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
    renderer: Literal['ufor', 'builtin'] = 'ufor'
    composition: dict[str, object] | None = None

    def document(self) -> dict[str, object]:
        return {
            'selector': self.selector,
            'title': self.title,
            'parameters': [parameter.document() for parameter in self.parameters],
            'renderer': self.renderer,
            'composition': self.composition,
        }


class AuthoringSession:
    def __init__(self, library: Library, config: AuthorConfig) -> None:
        self.library = library
        self.config = config
        self.animations = [
            *_author_animations(library, config.light_output),
            *_builtin_animations(),
        ]

    def preview(self, selector: str, parameters: dict[str, float]) -> dict[str, object]:
        selected = self._animation(selector)
        if selected.renderer == 'builtin':
            return _builtin_preview(
                selector.removeprefix('builtin:'), parameters, self.config.duration
            )
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

    def preset_document(
        self, selector: str, parameters: dict[str, float], name: str
    ) -> str:
        selected = self._animation(selector)
        if selected.renderer != 'ufor':
            raise ValueError(
                'built-in reactive effects cannot be saved as Ufor presets'
            )
        preset = PresetScore(
            name=name,
            title=f'{selected.title} preset',
            score=ScoreVersion(selector=selector),
            parameters=parameters,
        )
        entries = [
            entry.model_copy(
                update={
                    'state': State.pending,
                    'dependencies': {},
                    'resolved': None,
                    'content_origin': None,
                }
            )
            for entry in self.library.entries.values()
        ]
        address = f'/{name}.toml'
        validation_library = Library(
            [
                *entries,
                Entry(library='author', address=address, name=name, score=preset),
            ]
        )
        show.prepare_library_animation(
            validation_library,
            show.LightProgramSpec(
                selector=f'author:{address}', output=self.config.light_output
            ),
        )
        return codec.score_toml(preset)

    def operation_document(self, entry_key: str, output: str, template: str) -> str:
        entry = self.library.entries.get(entry_key)
        if entry is None or not isinstance(entry.score, AnimationScore):
            raise ValueError(
                'selected operation is not backed by a TOML animation score'
            )
        source = self._source_path(entry)
        if source.suffix != '.toml':
            raise ValueError(
                'selected operation is not backed by a TOML animation score'
            )
        document = tomlkit.parse(source.read_text())
        operation = _operation_template(template, entry.score)
        body = document.get('body')
        if not isinstance(body, Table):
            raise ValueError(f'{source}: animation body is missing')
        body['operation'] = tomlkit.item(operation.model_dump(mode='json'))
        text = tomlkit.dumps(document)
        edited = codec.parse_score(text)
        if not isinstance(edited, AnimationScore):
            raise ValueError(f'{source}: edited score is not an animation')
        validation_library = _validation_library(self.library, entry_key, edited)
        show.prepare_library_animation(
            validation_library,
            show.LightProgramSpec(selector=entry_key, output=output),
        )
        return text

    def _animation(self, selector: str) -> AuthorAnimation:
        for item in self.animations:
            if item.selector == selector:
                return item
        raise ValueError(f'unknown animation {selector!r}')

    def _source_path(self, entry: Entry) -> Path:
        config_path = library_files.configuration_path(self.config.library_config)
        config = LibraryConfig.model_validate(tomlkit.parse(config_path.read_text()))
        registration = next(
            (item for item in config.libraries if item.name == entry.library), None
        )
        if registration is None:
            raise ValueError(f'{entry.library}: library registration is missing')
        root = library_files.expanded_path(registration.root)
        if not root.is_absolute():
            root = config_path.parent / root
        return root / entry.address.removeprefix('/')


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


def _author_animations(library: Library, output: str) -> list[AuthorAnimation]:
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
                composition=_composition_tree(library, composition, output),
            )
        )
    return animations


def _composition_tree(
    library: Library, composition: Composition, output: str
) -> dict[str, object]:
    def node(path: str, output_name: str) -> dict[str, object]:
        part = composition.parts[path]
        score = composition.scores[part.score].score
        if not isinstance(score, AnimationScore):
            raise ValueError(f'{path}: score is not an animation')
        operation = score.body.operation
        entry = library.entries[part.score]
        children = []
        for source in light_animation.sources(operation):
            child = part.children[source.name]
            children.append(
                {
                    'source': source.name,
                    'output': source.output,
                    'node': node(child, source.output),
                }
            )
        return {
            'path': path,
            'output': output_name,
            'effect': operation.effect,
            'fields': operation.model_dump(mode='json'),
            'timeline': _operation_timeline(operation),
            'entry': entry.key,
            'editable': isinstance(entry.score, AnimationScore),
            'templates': _operation_templates(score),
            'children': children,
        }

    return node('root', output)


def _operation_timeline(operation: Model) -> dict[str, object] | None:
    if isinstance(operation, light_animation.Cues):
        end = max(cue.start + cue.duration for cue in operation.cues)
        return {
            'effect': operation.effect,
            'duration': _rational_text(end),
            'events': [
                {
                    'name': cue.source.name,
                    'output': cue.source.output,
                    'start': _rational_text(cue.start),
                    'duration': _rational_text(cue.duration),
                    'end': _rational_text(cue.start + cue.duration),
                }
                for cue in operation.cues
            ],
        }
    if isinstance(operation, light_animation.Crossfade):
        duration = _rational_text(operation.fade.duration)
        return {
            'effect': operation.effect,
            'duration': duration,
            'events': [
                {
                    'name': operation.outgoing.name,
                    'output': operation.outgoing.output,
                    'start': '0',
                    'duration': duration,
                    'end': duration,
                },
                {
                    'name': operation.incoming.name,
                    'output': operation.incoming.output,
                    'start': '0',
                    'duration': duration,
                    'end': duration,
                },
            ],
        }
    return None


def _rational_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else str(value)


def _operation_templates(score: AnimationScore) -> list[str]:
    stream = score.outputs[0].stream
    assert isinstance(stream, LightType)
    templates = ['fill']
    if stream.components == ['red', 'green', 'blue']:
        templates.extend(['aurora', 'color_fill', 'color_chase'])
    return templates


def _operation_template(template: str, score: AnimationScore) -> Model:
    stream = score.outputs[0].stream
    assert isinstance(stream, LightType)
    if template == 'fill':
        return light_animation.Fill(values=[0.0] * len(stream.components))
    if stream.components != ['red', 'green', 'blue']:
        raise ValueError(f'{template!r} requires red, green, blue components')
    effect_types = {
        'aurora': effects.Aurora,
        'color_fill': effects.ColorFill,
        'color_chase': effects.ColorChase,
    }
    effect_type = effect_types.get(template)
    if effect_type is None:
        raise ValueError(f'unknown operation template {template!r}')
    return effect_type()


def _validation_library(
    library: Library, entry_key: str, edited: AnimationScore
) -> Library:
    entries = [
        entry.model_copy(
            update={
                'score': edited if entry.key == entry_key else entry.score,
                'state': State.pending,
                'dependencies': {},
                'resolved': None,
                'content_origin': None,
            }
        )
        for entry in library.entries.values()
    ]
    return Library(entries)


def _builtin_animations() -> list[AuthorAnimation]:
    controls = {
        'audio-scan': [
            AuthorParameter('width', 0.02, 0.5, 0.12, 'ratio'),
            AuthorParameter('speed', 0, 2, 0.4, 'ratio'),
            AuthorParameter('sensitivity', 0, 4, 1.5, 'ratio'),
        ],
        'audio-spectrum': [
            AuthorParameter('gain', 0, 4, 1.5, 'ratio'),
            AuthorParameter('smoothing', 0, 30, 10, 'ratio'),
        ],
        'bass-pulse': [
            AuthorParameter('speed', 0.05, 2, 0.55, 'ratio'),
            AuthorParameter('decay', 0.1, 12, 3.5, 'ratio'),
        ],
        'audio-spotlights': [
            AuthorParameter('density', 0, 15, 4, 'ratio'),
            AuthorParameter('width', 0.01, 0.3, 0.08, 'ratio'),
            AuthorParameter('decay', 0.1, 10, 2.4, 'ratio'),
        ],
        'audio-waterfall': [AuthorParameter('speed', 0, 3, 0.7, 'ratio')],
        'audio-flame': [
            AuthorParameter('cooling', 0.1, 5, 1.2, 'ratio'),
            AuthorParameter('sparks', 0, 10, 2.5, 'ratio'),
        ],
        'beat-strobe': [AuthorParameter('decay', 0.1, 20, 8, 'ratio')],
    }
    return [
        AuthorAnimation(
            selector=f'builtin:{name}',
            title=name.replace('-', ' ').title(),
            parameters=parameters,
            renderer='builtin',
        )
        for name, parameters in controls.items()
    ]


def _builtin_preview(
    name: str, parameters: dict[str, float], duration: float
) -> dict[str, object]:
    renderer = reactive_effects.EFFECTS.get(name)
    if renderer is None:
        raise ValueError(f'unknown built-in animation {name!r}')
    source = cast(
        animation.Animation[reactive_effects.AudioState],
        renderer.model_validate(parameters),
    )
    device = animation.Device(led_count=128)
    state = source.initial_state(device)
    state.fps = 30
    frame_count = max(1, round(duration * state.fps))
    frames = []
    for index in range(frame_count):
        reactive_effects.update_features(state, _demo_features(index, frame_count))
        frame = animation.byte_light_frame_from_float(source.render(device, state))
        frames.append(b64encode(memoryview(frame).cast('B')).decode('ascii'))
    return {
        'coords': [[index, 0] for index in range(device.led_count)],
        'fps': state.fps,
        'frames': frames,
    }


def _demo_features(index: int, frame_count: int) -> reactivity.AudioFeatures:
    phase = index / max(1, frame_count - 1)
    level = 0.25 + 0.5 * (0.5 + 0.5 * math.sin(phase * math.tau * 3))
    onset = max(0, math.sin(phase * math.tau * 6)) ** 4
    return reactivity.AudioFeatures(
        level=level,
        bass=0.2 + onset * 0.8,
        mid=0.25 + 0.5 * (0.5 + 0.5 * math.sin(phase * math.tau * 2)),
        treble=0.3 + 0.4 * (0.5 + 0.5 * math.sin(phase * math.tau * 5)),
        onset=onset,
        beat=1 if onset > 0.9 else 0,
        spectrum=[
            max(0, math.sin(phase * math.tau * (band + 1) + band)) for band in range(16)
        ],
    )


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
            path = urlparse(self.path).path
            if path not in {'/api/preview', '/api/preset', '/api/operation'}:
                self.send_error(404)
                return
            try:
                payload = _request_json(self)
                response: dict[str, object]
                if path == '/api/operation':
                    entry = payload.get('entry')
                    output = payload.get('output')
                    template = payload.get('template')
                    if not all(
                        isinstance(value, str) for value in (entry, output, template)
                    ):
                        raise ValueError(
                            'operation requires entry, output, and template'
                        )
                    assert isinstance(entry, str)
                    assert isinstance(output, str)
                    assert isinstance(template, str)
                    response = {
                        'filename': Path(entry).name,
                        'document': session.operation_document(entry, output, template),
                    }
                else:
                    selector, parameters = _preview_request(payload)
                    if path == '/api/preview':
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
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {'error': str(error)})
                return
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


_AUTHOR_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lyte Author</title>
<style>
html,body{height:100%;margin:0;background:#111417;color:#e5e7eb;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{height:100%;display:grid;grid-template-columns:minmax(260px,340px) 1fr}
aside{border-right:1px solid #343a40;padding:16px;overflow:auto}canvas{width:100%;height:100%;display:block}
h1{font-size:17px;margin:0 0 16px}h2{font-size:13px;margin:24px 0 8px;color:#cbd5e1}label{display:grid;gap:6px;margin:14px 0;color:#cbd5e1}
select,input{width:100%;box-sizing:border-box}output,#status{font-variant-numeric:tabular-nums;color:#94a3b8}.transport{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}.transport button:last-child{grid-column:span 3}button{padding:7px;border:1px solid #475569;border-radius:4px;background:#1e293b;color:#e5e7eb}.transport label{display:flex;align-items:center;gap:6px;margin:10px 0}.transport label input{width:auto}#frame{margin:4px 0}#status{display:block;min-height:20px}.tree{margin:0;padding-left:16px}.tree li{margin:4px 0}.tree button{width:100%;text-align:left;padding:4px 6px}.tree button.selected{background:#334155}pre{margin:8px 0;max-height:220px;overflow:auto;padding:8px;background:#0b0f14;border:1px solid #343a40;border-radius:4px;font-size:12px;white-space:pre-wrap}
#timeline{display:grid;gap:7px}.timeline-summary{color:#94a3b8;font-variant-numeric:tabular-nums}.timeline-row{display:grid;grid-template-columns:78px 1fr;gap:6px;align-items:center}.timeline-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.timeline-track{height:22px;position:relative;background:#0b0f14;border:1px solid #343a40;border-radius:4px}.timeline-bar{height:100%;position:absolute;background:#2563eb;border-radius:3px;overflow:hidden;white-space:nowrap;box-sizing:border-box;padding:3px 5px;font-size:11px;color:#eff6ff}
@media(max-width:700px){main{grid-template-columns:1fr;grid-template-rows:auto 1fr}aside{border-right:0;border-bottom:1px solid #343a40}}
</style>
</head>
<body>
<main><aside><h1>Lyte Author</h1><label>Animation<select id="animation"></select></label><section id="controls"></section><h2>Composition</h2><section id="composition"></section><h2>Inspector</h2><pre id="inspector">Select an operation</pre><h2>Timeline</h2><section id="timeline">Select a timed operation</section><label>Replace selected operation<select id="operation-template" disabled></select></label><button id="download-operation" type="button" disabled>Download edited score</button><output id="operation-status"></output><h2>Save preset</h2><label>Name<input id="preset-name"></label><button id="save" type="button">Download TOML preset</button><output id="save-status"></output><h2>Preview</h2><div class="transport"><button id="previous" type="button" aria-label="Previous frame">Previous</button><button id="play" type="button">Pause</button><button id="next" type="button" aria-label="Next frame">Next</button><label><input id="loop" type="checkbox" checked>Loop</label></div><input id="frame" type="range" min="0" max="0" value="0" aria-label="Preview frame"><output id="status"></output></aside><canvas id="preview"></canvas></main>
<script>
const catalog=__LYTE_AUTHOR_CATALOG__;
const select=document.getElementById('animation');
const controls=document.getElementById('controls');
const canvas=document.getElementById('preview');
const context=canvas.getContext('2d');
const previous=document.getElementById('previous');
const play=document.getElementById('play');
const next=document.getElementById('next');
const loop=document.getElementById('loop');
const frameControl=document.getElementById('frame');
const status=document.getElementById('status');
const composition=document.getElementById('composition');
const inspector=document.getElementById('inspector');
const timeline=document.getElementById('timeline');
const operationTemplate=document.getElementById('operation-template');
const downloadOperation=document.getElementById('download-operation');
const operationStatus=document.getElementById('operation-status');
const presetName=document.getElementById('preset-name');
const save=document.getElementById('save');
const saveStatus=document.getElementById('save-status');
let preview=null;
let frames=[];
let frame=0;
let playing=true;
let lastTime=0;
let previewRequest=0;
let selectedOperation=null;
for(const animation of catalog){const option=document.createElement('option');option.value=animation.selector;option.textContent=animation.title;select.append(option)}
function active(){return catalog.find(animation=>animation.selector===select.value)}
function values(){return Object.fromEntries([...controls.querySelectorAll('input')].map(input=>[input.name,Number(input.value)]))}
function control(parameter){const label=document.createElement('label');label.textContent=parameter.name;const input=document.createElement('input');input.type='range';input.name=parameter.name;input.min=parameter.minimum;input.max=parameter.maximum;input.step=(parameter.maximum-parameter.minimum)/200||1;input.value=parameter.default;const output=document.createElement('output');output.textContent=`${parameter.default} ${parameter.unit}`;input.oninput=()=>{output.textContent=`${input.value} ${parameter.unit}`;requestPreview()};label.append(input,output);controls.append(label)}
function defaultPresetName(){return `preset-${select.value.replace(/[^A-Za-z0-9_-]+/g,'-').replace(/^-+|-+$/g,'')||'animation'}`}
function rationalNumber(value){const [numerator,denominator='1']=value.split('/');return Number(numerator)/Number(denominator)}
function rebuildTimeline(node){timeline.replaceChildren();if(!node.timeline){timeline.textContent='This operation has no timed cues or crossfade.';return}const summary=document.createElement('div');summary.className='timeline-summary';summary.textContent=`${node.timeline.effect} · ${node.timeline.duration} s`;timeline.append(summary);const duration=rationalNumber(node.timeline.duration);for(const event of node.timeline.events){const row=document.createElement('div');row.className='timeline-row';const label=document.createElement('div');label.className='timeline-label';label.textContent=`${event.name}:${event.output}`;label.title=label.textContent;const track=document.createElement('div');track.className='timeline-track';const bar=document.createElement('div');bar.className='timeline-bar';bar.style.left=`${rationalNumber(event.start)/duration*100}%`;bar.style.width=`${rationalNumber(event.duration)/duration*100}%`;bar.textContent=`${event.start}–${event.end} s`;track.append(bar);row.append(label,track);timeline.append(row)}}
function inspect(node,button){selectedOperation=node;inspector.textContent=JSON.stringify(node.fields,null,2);rebuildTimeline(node);operationTemplate.replaceChildren();operationStatus.textContent='';const placeholder=document.createElement('option');placeholder.textContent='Choose a template';placeholder.value='';operationTemplate.append(placeholder);for(const name of node.templates){const option=document.createElement('option');option.value=name;option.textContent=name;operationTemplate.append(option)}operationTemplate.disabled=!node.editable;downloadOperation.disabled=!node.editable;for(const item of composition.querySelectorAll('button')){item.classList.remove('selected')}button.classList.add('selected')}
function compositionNode(node){const item=document.createElement('li');const button=document.createElement('button');button.type='button';button.textContent=`${node.path} · ${node.effect}`;button.onclick=()=>inspect(node,button);item.append(button);if(node.children.length){const children=document.createElement('ul');children.className='tree';for(const child of node.children){const branch=document.createElement('li');branch.textContent=`${child.source}:${child.output}`;const nested=document.createElement('ul');nested.className='tree';nested.append(compositionNode(child.node));branch.append(nested);children.append(branch)}item.append(children)}return item}
function rebuildComposition(){composition.replaceChildren();const tree=active().composition;if(!tree){inspector.textContent='This animation has no Ufor composition.';return}const nodes=document.createElement('ul');nodes.className='tree';nodes.append(compositionNode(tree));composition.append(nodes);const first=composition.querySelector('button');if(first){first.click()}}
function rebuild(){controls.replaceChildren();for(const parameter of active().parameters){control(parameter)}rebuildComposition();presetName.value=defaultPresetName();saveStatus.textContent='';requestPreview()}
function decodeFrame(text){const binary=atob(text);const bytes=new Uint8Array(binary.length);for(let index=0;index<binary.length;index+=1){bytes[index]=binary.charCodeAt(index)}return bytes}
async function requestPreview(){const request=++previewRequest;const response=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selector:select.value,parameters:values()})});if(request!==previewRequest){return}if(!response.ok){const error=await response.json();status.textContent=error.error;return}preview=await response.json();frames=preview.frames.map(decodeFrame);frame=0;frameControl.max=Math.max(0,frames.length-1);frameControl.value=frame;updateStatus()}
async function savePreset(){const response=await fetch('/api/preset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selector:select.value,parameters:values(),name:presetName.value})});const result=await response.json();if(!response.ok){saveStatus.textContent=result.error;return}const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([result.document],{type:'application/toml'}));link.download=result.filename;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),0);saveStatus.textContent=`Downloaded ${result.filename}`}
async function saveOperation(){if(!selectedOperation||!operationTemplate.value){operationStatus.textContent='Choose an operation template';return}const response=await fetch('/api/operation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entry:selectedOperation.entry,output:selectedOperation.output,template:operationTemplate.value})});const result=await response.json();if(!response.ok){operationStatus.textContent=result.error;return}const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([result.document],{type:'application/toml'}));link.download=result.filename;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),0);operationStatus.textContent=`Downloaded ${result.filename}`}
function updateStatus(){if(!preview){status.textContent='Loading preview';return}status.textContent=`${active().title} · frame ${frame+1} of ${frames.length} · ${preview.fps} FPS`}
function setFrame(value){if(!frames.length){return}if(value<0){frame=loop.checked?frames.length-1:0}else if(value>=frames.length){frame=loop.checked?0:frames.length-1;playing=loop.checked}else{frame=value}frameControl.value=frame;updateStatus()}
function resize(){const scale=devicePixelRatio||1;const rect=canvas.getBoundingClientRect();canvas.width=Math.max(1,Math.round(rect.width*scale));canvas.height=Math.max(1,Math.round(rect.height*scale))}
function projectedPoints(){const bounds=preview.coords.reduce((value,point)=>({minX:Math.min(value.minX,point[0]),minY:Math.min(value.minY,point[1]),maxX:Math.max(value.maxX,point[0]),maxY:Math.max(value.maxY,point[1])}),{minX:Infinity,minY:Infinity,maxX:-Infinity,maxY:-Infinity});const pad=Math.max(24,Math.min(canvas.width,canvas.height)*0.08);const spanX=Math.max(1e-9,bounds.maxX-bounds.minX);const spanY=Math.max(1e-9,bounds.maxY-bounds.minY);const scale=Math.min((canvas.width-pad*2)/spanX,(canvas.height-pad*2)/spanY);const offsetX=(canvas.width-spanX*scale)/2;const offsetY=(canvas.height-spanY*scale)/2;return preview.coords.map(point=>[offsetX+(point[0]-bounds.minX)*scale,offsetY+(point[1]-bounds.minY)*scale])}
function draw(){context.fillStyle='#050506';context.fillRect(0,0,canvas.width,canvas.height);if(!preview||!frames.length){return}const points=projectedPoints();const values=frames[frame];const radius=Math.max(3,Math.min(canvas.width,canvas.height)/140);for(let index=0;index<points.length;index+=1){const offset=index*3;context.fillStyle=`rgb(${values[offset]},${values[offset+1]},${values[offset+2]})`;context.beginPath();context.arc(points[index][0],points[index][1],radius,0,Math.PI*2);context.fill()}}
function animate(time){if(playing&&preview&&frames.length){const elapsed=time-lastTime;const advance=Math.floor(elapsed*preview.fps/1000);if(advance>0){setFrame(frame+advance);lastTime=time}}else{lastTime=time}draw();requestAnimationFrame(animate)}
select.onchange=rebuild;save.onclick=savePreset;downloadOperation.onclick=saveOperation;previous.onclick=()=>{playing=false;play.textContent='Play';setFrame(frame-1)};next.onclick=()=>{playing=false;play.textContent='Play';setFrame(frame+1)};play.onclick=()=>{playing=!playing;play.textContent=playing?'Pause':'Play'};frameControl.oninput=()=>{playing=false;play.textContent='Play';setFrame(Number(frameControl.value))};addEventListener('resize',resize);resize();rebuild();requestAnimationFrame(animate);
</script></body></html>"""

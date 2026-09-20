"""WLED snapshot interchange, explicit score translation, and DDP encoding."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import tyro
from reccy.runtime import logging

LOGGER = logging.get_logger(__name__)
_SOURCE_FILES = {
    'presets': 'presets.json',
    'effects': 'eff.json',
    'fxdata': 'fxdata.json',
    'palettes': 'pal.json',
    'info': 'info.json',
}


class WledError(ValueError):
    pass


WledAction = Literal['import', 'export', 'list', 'translate']


@dataclass(frozen=True)
class WledCommandConfig:
    action: Annotated[WledAction, tyro.conf.Positional] = 'list'
    input: Annotated[Path, tyro.conf.Positional] = Path('wled-snapshot.json')
    output: Path | None = None


@dataclass(frozen=True)
class WledPreset:
    identifier: str
    name: str | None
    effect: str | None
    raw: dict[str, object]


@dataclass(frozen=True)
class WledSnapshot:
    raw: dict[str, object]
    source_hashes: dict[str, str]
    presets: list[WledPreset]
    effects: list[str]
    controller_name: str | None
    led_count: int | None

    def document(self) -> dict[str, object]:
        raw = _without_network_identity(self.raw)
        assert isinstance(raw, dict)
        return {
            'format': 'lyte-wled-snapshot',
            'version': 1,
            'source_hashes': self.source_hashes,
            'raw': raw,
        }


@dataclass(frozen=True)
class Translation:
    wled_effect: str
    lyte_effect: str
    difference: str


TRANSLATIONS = {
    'solid': Translation(
        'Solid', 'color_fill', 'WLED segment and transition state is not retained.'
    ),
    'breathe': Translation(
        'Breathe', 'color_fade', 'lyte uses its own symmetric brightness curve.'
    ),
    'chase': Translation(
        'Chase', 'color_chase', 'WLED background and secondary colors are not retained.'
    ),
    'chase rainbow': Translation(
        'Chase Rainbow',
        'rainbow',
        'lyte renders a moving rainbow rather than WLED chase blocks.',
    ),
    'candle': Translation(
        'Candle', 'candle_bank', 'lyte uses deterministic seeded candle zones.'
    ),
    'color wipe': Translation(
        'Color Wipe', 'color_wipe', 'WLED transition state is not retained.'
    ),
    'comet': Translation('Comet', 'larson_scanner', 'lyte reflects at strip ends.'),
    'rainbow': Translation(
        'Rainbow', 'rainbow', 'WLED palette and segment options are not retained.'
    ),
    'scan': Translation(
        'Scan', 'larson_scanner', 'lyte tail and bounce behavior differ.'
    ),
    'twinkle': Translation(
        'Twinkle', 'twinkle', 'lyte random timing is independently seeded.'
    ),
}


def run_wled_command(config: WledCommandConfig) -> int:
    if config.action == 'import':
        if config.output is None:
            raise WledError('import requires --output')
        write_snapshot(config.output, import_snapshot(config.input))
        return 0
    snapshot = read_snapshot(config.input)
    if config.action == 'export':
        if config.output is None:
            raise WledError('export requires --output')
        write_native_presets(config.output, snapshot)
        return 0
    if config.action == 'list':
        list_presets(snapshot.presets)
        return 0
    if config.output is None:
        raise WledError('translate requires --output')
    translate_snapshot(snapshot, config.output)
    return 0


def import_snapshot(path: Path) -> WledSnapshot:
    raw, source_hashes = _read_source_documents(path)
    return _snapshot_from_raw(raw, source_hashes)


def read_snapshot(path: Path) -> WledSnapshot:
    document = _read_json_object(path)
    if document.get('format') != 'lyte-wled-snapshot' or document.get('version') != 1:
        raise WledError(f'{path}: not a lyte WLED snapshot')
    raw = document.get('raw')
    hashes = document.get('source_hashes')
    if not isinstance(raw, dict) or not isinstance(hashes, dict):
        raise WledError(f'{path}: snapshot requires raw data and source hashes')
    if not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in hashes.items()
    ):
        raise WledError(f'{path}: source hashes must be string values')
    sanitized = _without_network_identity(raw)
    assert isinstance(sanitized, dict)
    return _snapshot_from_raw(sanitized, hashes)


def write_snapshot(path: Path, snapshot: WledSnapshot) -> None:
    _write_json(path, snapshot.document())


def write_native_presets(path: Path, snapshot: WledSnapshot) -> None:
    presets = snapshot.raw['presets']
    assert isinstance(presets, dict)
    _write_json(path, presets)


def list_presets(presets: Iterable[WledPreset]) -> None:
    for preset in presets:
        effect = preset.effect or 'unknown effect'
        translation = (
            'translated' if effect.casefold() in TRANSLATIONS else 'native only'
        )
        name = preset.name or 'unnamed'
        print(f'{preset.identifier}\t{name}\t{effect}\t{translation}')


def translate_snapshot(snapshot: WledSnapshot, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for preset in snapshot.presets:
        translated = translate_preset(preset, snapshot.led_count)
        entry: dict[str, object] = {
            'preset_id': preset.identifier,
            'name': preset.name,
            'wled_effect': preset.effect,
        }
        if translated is None:
            entry['not_translated'] = _translation_failure(preset)
        else:
            filename = (
                f'{_safe_name(preset.identifier)}-'
                f'{_safe_name(preset.name or "preset")}.toml'
            )
            destination = output / filename
            if destination.exists():
                raise WledError(f'{destination}: refusing to overwrite generated score')
            destination.write_text(
                _score_document(preset, translated, snapshot.led_count)
            )
            entry['score'] = filename
            entry['lyte_effect'] = translated.lyte_effect
            entry['difference'] = translated.difference
        manifest.append(entry)
    destination = output / 'manifest.json'
    _write_json(
        destination, {'format': 'lyte-wled-translation-manifest', 'presets': manifest}
    )
    return destination


def translate_preset(preset: WledPreset, led_count: int | None) -> Translation | None:
    if preset.effect is None or preset.effect.casefold() not in TRANSLATIONS:
        return None
    segments = preset.raw.get('seg')
    if not isinstance(segments, list) or len(segments) != 1:
        return None
    if not isinstance(segments[0], dict):
        return None
    if led_count is not None and led_count <= 0:
        return None
    return TRANSLATIONS[preset.effect.casefold()]


def _read_source_documents(path: Path) -> tuple[dict[str, object], dict[str, str]]:
    if not path.is_dir():
        raise WledError(f'{path}: WLED import input must be a directory')
    raw: dict[str, object] = {}
    hashes: dict[str, str] = {}
    metadata_path = path / 'metadata.json'
    metadata = _read_json_object(metadata_path) if metadata_path.exists() else None
    for name, filename in _SOURCE_FILES.items():
        source = path / filename
        if source.exists():
            raw[name] = _without_network_identity(_read_json_value(source))
            hashes[filename] = _sha256(source)
        elif metadata is not None and name in metadata:
            raw[name] = _without_network_identity(metadata[name])
            hashes['metadata.json'] = _sha256(metadata_path)
        else:
            raise WledError(
                f'{path}: missing {filename} or metadata.json field {name!r}'
            )
    return raw, hashes


def _snapshot_from_raw(raw: dict[str, object], hashes: dict[str, str]) -> WledSnapshot:
    required = set(_SOURCE_FILES)
    if missing := sorted(required - set(raw)):
        raise WledError(f'snapshot missing source data: {", ".join(missing)}')
    presets_raw = raw['presets']
    effects_raw = raw['effects']
    info_raw = raw['info']
    if not isinstance(presets_raw, dict):
        raise WledError('presets.json must contain an object')
    if not isinstance(effects_raw, list) or not all(
        isinstance(value, str) for value in effects_raw
    ):
        raise WledError('effects.json must contain an array of effect names')
    if not isinstance(info_raw, dict):
        raise WledError('info.json must contain an object')
    presets = [
        _parse_preset(identifier, value, effects_raw)
        for identifier, value in presets_raw.items()
    ]
    return WledSnapshot(
        raw,
        hashes,
        presets,
        effects_raw,
        _string(info_raw.get('name')),
        _led_count(info_raw),
    )


def _parse_preset(identifier: object, value: object, effects: list[str]) -> WledPreset:
    if not isinstance(identifier, str) or not isinstance(value, dict):
        raise WledError('presets.json must map preset IDs to objects')
    segments = value.get('seg')
    if not isinstance(segments, list) or not segments:
        return WledPreset(identifier, _string(value.get('n')), None, value)
    first = segments[0]
    if not isinstance(first, dict):
        raise WledError(f'preset {identifier}: segment must be an object')
    effect_id = first.get('fx')
    if effect_id is None:
        return WledPreset(identifier, _string(value.get('n')), None, value)
    if isinstance(effect_id, bool) or not isinstance(effect_id, int):
        raise WledError(f'preset {identifier}: segment fx must be an integer')
    if not 0 <= effect_id < len(effects):
        raise WledError(f'preset {identifier}: effect ID {effect_id} is unavailable')
    return WledPreset(identifier, _string(value.get('n')), effects[effect_id], value)


def _translation_failure(preset: WledPreset) -> str:
    if preset.effect is None:
        return 'preset has no resolvable WLED effect'
    if preset.effect.casefold() not in TRANSLATIONS:
        return f'WLED effect {preset.effect!r} has no declared lyte translation'
    segments = preset.raw.get('seg')
    if not isinstance(segments, list) or len(segments) != 1:
        return 'translation currently requires exactly one WLED segment'
    return 'preset does not satisfy the declared translation input range'


def _score_document(
    preset: WledPreset, translation: Translation, led_count: int | None
) -> str:
    segment = preset.raw['seg']
    assert isinstance(segment, list)
    first = segment[0]
    assert isinstance(first, dict)
    count = led_count or _segment_count(first) or 1
    operation = _operation(translation.lyte_effect, first, preset.raw)
    lines = [
        'format = "recs"',
        'version = 4',
        f'name = {_toml_string(_safe_name(preset.name or preset.identifier))}',
        f'title = {_toml_string(preset.name or "WLED preset")}',
        'inputs = []',
        'parameters = []',
        'kind = "animation"',
        '',
        '[[timebases]]',
        'name = "frames"',
        'kind = "physical"',
        '',
        '[timebases.rate]',
        'numerator = 20',
        'denominator = 1',
        '',
        '[[outputs]]',
        'name = "light"',
        '',
        '[outputs.stream]',
        'family = "sampled"',
        'quantity = "light"',
        'timebase = "frames"',
        'components = ["red", "green", "blue"]',
        'interpretation = "drive"',
        '',
        '[outputs.stream.layout]',
        'name = "wled_strip"',
        'axes = ["x"]',
        'unit = "unitless"',
        '',
    ]
    for index in range(count):
        lines.extend(
            [
                '[[outputs.stream.layout.lights]]',
                f'name = "light_{index}"',
                f'position = [{float(index)}]',
                '',
            ]
        )
    lines.extend(
        [
            '[outputs.stream.layout.regions]',
            '',
            '[outputs.binding]',
            'light = true',
            '',
            '[body]',
            'parts = []',
            'controls = []',
            '',
            '[body.operation]',
        ]
    )
    lines.extend(
        f'{key} = {_toml_value(value)}'
        for key, value in operation.items()
        if value is not None
    )
    lines.extend(
        ['', '[body.modulation]', 'parameters = []', 'sources = []', 'routes = []', '']
    )
    return '\n'.join(lines)


def _operation(
    effect: str, segment: dict[str, object], preset: dict[str, object]
) -> dict[str, object]:
    color = _scaled_color(segment, preset)
    speed = _integer(segment.get('sx'), 128)
    intensity = _integer(segment.get('ix'), 128)
    if effect == 'color_fill':
        return {'effect': effect, 'color': color}
    if effect == 'color_fade':
        return {'effect': effect, 'colors': [color], 'level_step': max(1, 256 - speed)}
    if effect == 'color_chase':
        return {
            'effect': effect,
            'color': color,
            'width': max(1, intensity // 32),
            'step': max(1, speed // 32),
        }
    if effect == 'candle_bank':
        return {
            'effect': effect,
            'color': color,
            'zone_size': max(1, intensity // 16),
            'base_level': 0.55,
            'flicker': 0.18,
            'flare_rate': speed / 255,
            'speed': 1.0,
            'seed': None,
        }
    if effect == 'color_wipe':
        return {
            'effect': effect,
            'color': color,
            'start': 0,
            'end': None,
            'step': max(1, speed // 32),
        }
    if effect == 'larson_scanner':
        return {
            'effect': effect,
            'color': color,
            'tail': max(0, intensity // 32),
            'start': 0,
            'end': None,
            'step': max(1, speed // 32),
            'rainbow': False,
        }
    if effect == 'twinkle':
        return {
            'effect': effect,
            'colors': [color],
            'density': max(2, intensity * 100 // 255),
            'speed': max(2, speed * 100 // 255),
            'max_bright': 255,
            'seed': None,
        }
    return {'effect': 'rainbow', 'start': 0, 'end': None, 'step': max(1, speed // 32)}


def _scaled_color(segment: dict[str, object], preset: dict[str, object]) -> list[int]:
    colors = segment.get('col')
    raw = colors[0] if isinstance(colors, list) and colors else None
    if (
        not isinstance(raw, list)
        or len(raw) < 3
        or any(
            isinstance(value, bool) or not isinstance(value, int) for value in raw[:3]
        )
    ):
        return [255, 255, 255]
    brightness = _integer(preset.get('bri'), 255) * _integer(segment.get('bri'), 255)
    return [
        max(0, min(255, round(value * brightness / (255 * 255)))) for value in raw[:3]
    ]


def _segment_count(segment: dict[str, object]) -> int | None:
    start = segment.get('start')
    stop = segment.get('stop')
    if (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(stop, int)
        and not isinstance(stop, bool)
        and stop > start
    ):
        return stop - start
    return None


def _led_count(info: dict[str, object]) -> int | None:
    leds = info.get('leds')
    if not isinstance(leds, dict):
        return None
    count = leds.get('count')
    return (
        count
        if isinstance(count, int) and not isinstance(count, bool) and count > 0
        else None
    )


def _integer(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, min(255, value))
    return default


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _read_json_object(path: Path) -> dict[str, object]:
    value = _read_json_value(path)
    if not isinstance(value, dict):
        raise WledError(f'{path}: expected a JSON object')
    return value


def _read_json_value(path: Path) -> object:
    try:
        with path.open() as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise WledError(f'{path}: {error}') from error


def _without_network_identity(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_network_identity(item)
            for key, item in value.items()
            if key.casefold()
            not in {'host', 'ip', 'mac', 'macaddress', 'ssid', 'token'}
        }
    if isinstance(value, list):
        return [_without_network_identity(item) for item in value]
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_name(value: str) -> str:
    return (
        ''.join(character if character.isalnum() else '-' for character in value).strip(
            '-'
        )
        or 'preset'
    )


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_value(value: object) -> str:
    if value is None:
        raise ValueError('TOML does not represent null values')
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join(_toml_value(item) for item in value) + ']'
    raise TypeError(f'unsupported TOML value {type(value).__name__}')

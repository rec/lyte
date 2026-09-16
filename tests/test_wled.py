from __future__ import annotations

import json
import tomllib
from pathlib import Path

import numpy as np
import pytest
from ufor import library_files

from lyte import wled


def test_snapshot_round_trip_preserves_native_presets_and_excludes_network_identity(
    tmp_path: Path,
) -> None:
    source = write_snapshot_input(tmp_path / 'source')

    snapshot = wled.import_snapshot(source)
    destination = tmp_path / 'snapshot.json'
    wled.write_snapshot(destination, snapshot)
    exported = tmp_path / 'presets.json'
    wled.write_native_presets(exported, wled.read_snapshot(destination))

    assert json.loads(exported.read_text()) == json.loads(
        (source / 'presets.json').read_text()
    )
    document = destination.read_text()
    assert '192.168.1.25' not in document
    assert 'aa:bb:cc:dd:ee:ff' not in document
    assert 'secret-token' not in document
    assert snapshot.effects == ['Solid', 'Noise']
    assert snapshot.led_count == 4


def test_translation_generates_supported_score_and_preserves_unsupported_preset(
    tmp_path: Path,
) -> None:
    snapshot = wled.import_snapshot(write_snapshot_input(tmp_path / 'source'))

    manifest_path = wled.translate_snapshot(snapshot, tmp_path / 'scores')

    manifest = json.loads(manifest_path.read_text())
    translated, native = manifest['presets']
    assert translated['lyte_effect'] == 'color_fill'
    assert (
        native['not_translated']
        == "WLED effect 'Noise' has no declared lyte translation"
    )
    score = tomllib.loads((tmp_path / 'scores' / translated['score']).read_text())
    assert score['body']['operation'] == {'effect': 'color_fill', 'color': [64, 32, 16]}
    assert len(score['outputs'][0]['stream']['layout']['lights']) == 4
    library_config = tmp_path / 'library.toml'
    library_config.write_text('[[libraries]]\nname = "wled"\nroot = "scores"\n')
    library = library_files.read_library(library_config)
    assert [entry.name for entry in library.find()] == ['Red']


def test_ddp_encoder_uses_rgb_offsets_and_pushes_only_final_packet() -> None:
    frame = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)

    packets = wled.encode_ddp_frame(frame, sequence=7, maximum_payload_size=3)

    assert packets == [
        bytes([0x40, 7, 1, 0, 0, 0, 0, 0, 0, 3, 1, 2, 3]),
        bytes([0x41, 7, 1, 0, 0, 0, 0, 3, 0, 3, 4, 5, 6]),
    ]


@pytest.mark.parametrize(
    ('effect', 'lyte_effect'),
    [
        ('Solid', 'color_fill'),
        ('Breathe', 'color_fade'),
        ('Chase', 'color_chase'),
        ('Chase Rainbow', 'rainbow'),
        ('Candle', 'candle_bank'),
        ('Color Wipe', 'color_wipe'),
        ('Comet', 'larson_scanner'),
        ('Rainbow', 'rainbow'),
        ('Scan', 'larson_scanner'),
        ('Twinkle', 'twinkle'),
    ],
)
def test_each_declared_wled_effect_has_an_explicit_translation(
    effect: str, lyte_effect: str
) -> None:
    preset = wled.WledPreset('1', effect, effect, {'seg': [{'fx': 0}]})

    translation = wled.translate_preset(preset, led_count=10)

    assert translation is not None
    assert translation.lyte_effect == lyte_effect


def test_ddp_output_scales_before_sending() -> None:
    socket = FakeSocket()
    output = wled.WledDdpOutput('wled.local', 3, socket_factory=lambda *_: socket)
    frame = np.array([[0, 0, 0], [255, 0, 0]], dtype=np.uint8)

    packets = output.send(frame)

    assert packets == 1
    assert socket.sent[0][0][10:] == bytes([0, 0, 0, 0, 0, 0, 255, 0, 0])
    assert socket.sent[0][1] == ('wled.local', 4048)
    output.close()
    assert socket.closed


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, packet: bytes, address: tuple[str, int]) -> None:
        self.sent.append((packet, address))

    def close(self) -> None:
        self.closed = True


def write_snapshot_input(path: Path) -> Path:
    path.mkdir()
    (path / 'presets.json').write_text(
        json.dumps(
            {
                '1': {
                    'n': 'Red',
                    'bri': 128,
                    'unknown': {'keep': True},
                    'seg': [
                        {
                            'fx': 0,
                            'bri': 255,
                            'col': [[128, 64, 32], [0, 0, 0], [0, 0, 0]],
                            'sx': 128,
                            'ix': 128,
                            'start': 0,
                            'stop': 4,
                        }
                    ],
                },
                '2': {'n': 'Native only', 'seg': [{'fx': 1}]},
            }
        )
    )
    (path / 'eff.json').write_text(json.dumps(['Solid', 'Noise']))
    (path / 'fxdata.json').write_text(json.dumps([]))
    (path / 'pal.json').write_text(json.dumps([]))
    (path / 'info.json').write_text(
        json.dumps(
            {
                'name': 'Stage WLED',
                'ip': '192.168.1.25',
                'mac': 'aa:bb:cc:dd:ee:ff',
                'token': 'secret-token',
                'leds': {'count': 4},
            }
        )
    )
    return path

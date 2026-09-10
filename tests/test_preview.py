from __future__ import annotations

import base64
import json
from pathlib import Path

from ufor import light_animation
from ufor.interface import LightBinding, Output
from ufor.library import Entry, Library
from ufor.lights import LightType, rings
from ufor.time import Rate, Timebase

from lyte import rendering, show
from lyte.preview import document


def preview_data(value: str) -> dict[str, object]:
    start = value.index('const data = ') + len('const data = ')
    end = value.index(';\nconst canvas', start)
    return json.loads(value[start:end])


def test_animation_document_uses_authored_ring_coordinates() -> None:
    layout = rings([4, 8], [1.0, 2.0])
    value = light_animation.AnimationScore(
        name='rings',
        title='Rings',
        timebases=[Timebase(name='frames', rate=Rate(numerator=2))],
        outputs=[
            Output(
                name='light',
                stream=LightType(
                    timebase='frames',
                    components=['red', 'green', 'blue'],
                    layout=layout,
                ),
                binding=LightBinding(),
            )
        ],
        body=light_animation.Animation(
            operation=light_animation.Fill(values=[1 / 255, 2 / 255, 3 / 255])
        ),
    )
    library = Library(
        [Entry(library='test', address='/rings.toml', name='rings', score=value)]
    )
    prepared = rendering.PreparedAnimation(
        library, library.composition('rings'), 'light'
    )

    data = preview_data(
        document.animation_document(
            prepared, duration=1, led_size=2.5, name='Concentric rings'
        )
    )

    assert data['name'] == 'Concentric rings'
    assert data['coords'] == [light.position for light in layout.lights]
    assert data['ledSize'] == 2.5
    frames = data['frames']
    assert isinstance(frames, list)
    assert len(frames) == 2
    assert base64.b64decode(frames[0]) == bytes([1, 2, 3] * 12)


def test_one_dimensional_layout_is_padded_for_canvas_projection() -> None:
    prepared = show.prepare_animation(
        show.LightProgramSpec(selector='examples:/ripple.toml'),
        Path('examples/library.toml'),
    )

    data = preview_data(document.animation_document(prepared, duration=0.05))

    assert data['coords'][0] == [0.0, 0.0]
    assert data['coords'][-1] == [124.0, 0.0]

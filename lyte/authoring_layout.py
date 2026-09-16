"""Edit logical coordinates without changing light identity or wiring."""

from math import isfinite

import tomlkit
from ufor.light_animation import AnimationScore
from ufor.lights import Layout, LightType


def layout_document(source: str, score: AnimationScore, positions: list[object]) -> str:
    stream = score.outputs[0].stream
    assert isinstance(stream, LightType)
    if len(positions) != len(stream.layout.lights):
        raise ValueError('positions require one row per logical light')
    layout = Layout.model_validate(
        stream.layout.model_dump(mode='json')
        | {
            'lights': [
                {'name': p.name, 'position': v}
                for p, v in zip(stream.layout.lights, positions, strict=True)
            ]
        }
    )
    if any(not isfinite(v) for p in layout.lights for v in p.position):
        raise ValueError('light coordinates must be finite')
    document = tomlkit.parse(source)
    lights = document['outputs'][0]['stream']['layout']['lights']
    for light, edited in zip(lights, layout.lights, strict=True):
        light['position'] = tomlkit.item(edited.position)
    return tomlkit.dumps(document)

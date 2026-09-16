"""Explicit RGB field support for the animation editor."""

from math import isfinite

import tomlkit
from tomlkit.items import Table
from ufor import effects, light_animation
from ufor.lights import Interpretation, LightType

from .authoring_composition import update_table


def color_fields(score: light_animation.AnimationScore) -> dict[str, object]:
    operation = score.body.operation
    field = _RGB_FIELDS.get(type(operation))
    if field is not None:
        return {
            field: {
                'kind': 'palette' if field == 'palette' else 'rgb',
                'scale': 255,
                'values': operation.model_dump(mode='json')[field],
            }
        }
    stream = score.outputs[0].stream
    if (
        isinstance(operation, light_animation.Fill)
        and isinstance(stream, LightType)
        and stream.components == ['red', 'green', 'blue']
        and stream.interpretation == Interpretation.drive
    ):
        return {'values': {'kind': 'rgb', 'scale': 1, 'values': operation.values}}
    return {}


def color_document(
    source: str, score: light_animation.AnimationScore, fields: dict[str, object]
) -> str:
    if not fields or fields.keys() != color_fields(score).keys():
        raise ValueError('colour fields do not match the supported operation fields')
    operation = type(score.body.operation).model_validate(
        score.body.operation.model_dump(mode='json') | fields
    )
    if isinstance(operation, light_animation.Fill) and any(
        not isfinite(v) for v in operation.values
    ):
        raise ValueError('RGB drive values must be finite')
    document = tomlkit.parse(source)
    body = document.get('body')
    if not isinstance(body, Table) or not isinstance(body.get('operation'), Table):
        raise ValueError('animation operation is missing')
    values = operation.model_dump(mode='json')
    update_table(
        body['operation'], {k: values[k] for k in fields}, remove_missing=False
    )
    return tomlkit.dumps(document)


_RGB_FIELDS = {
    effects.Aurora: 'palette',
    effects.ExpandingRipples: 'palette',
    effects.ColorChase: 'color',
    effects.ColorFill: 'color',
}

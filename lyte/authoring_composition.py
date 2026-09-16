"""Comment-preserving edits to a score's declared composition structure."""

from collections.abc import Mapping

import tomlkit
from tomlkit.items import Table
from ufor.light_animation import AnimationScore


def composition_document(
    source: str, score: AnimationScore, structure: dict[str, object]
) -> str:
    if set(structure) != {'parts', 'operation'}:
        raise ValueError('composition requires parts and operation')
    # Validate the complete body, including exports and existing modulation.
    edited = AnimationScore.model_validate(
        score.model_dump(mode='json')
        | {'body': score.body.model_dump(mode='json') | structure}
    )
    document = tomlkit.parse(source)
    body = document.get('body')
    if not isinstance(body, Table):
        raise ValueError('animation body is missing')
    update_table(
        body,
        {
            'parts': [
                p.model_dump(mode='json', exclude_none=True) for p in edited.body.parts
            ],
            'operation': edited.body.operation.model_dump(
                mode='json', exclude_none=True
            ),
        },
        remove_missing=False,
    )
    return tomlkit.dumps(document)


def update_table(
    table: Table, values: Mapping[str, object], *, remove_missing: bool = True
) -> None:
    if remove_missing:
        for name in list(table):
            if name not in values:
                del table[name]
    for name, value in values.items():
        existing = table.get(name)
        if existing == value:
            continue
        if isinstance(existing, Table) and isinstance(value, dict):
            update_table(existing, value)
        else:
            table[name] = tomlkit.item(value)

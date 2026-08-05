from __future__ import annotations

import os

import pytest

from lyte.animations.hamiltonian import RGB, hamiltonian_colors

RUN_HAMILTONIAN_CHECK = 'LYTE_RUN_HAMILTONIAN_CHECK'

pytestmark = pytest.mark.skipif(
    os.environ.get(RUN_HAMILTONIAN_CHECK) != '1',
    reason=f'set {RUN_HAMILTONIAN_CHECK}=1 to run the Hamiltonian sequence check',
)


def test_hamiltonian_sequence_has_single_channel_steps() -> None:
    n = int(os.environ.get('LYTE_HAMILTONIAN_N', '32'))
    order = os.environ.get('LYTE_HAMILTONIAN_ORDER', 'rgb')
    inverted = os.environ.get('LYTE_HAMILTONIAN_INVERTED', '')
    colors = list(hamiltonian_colors(n=n, order=order, inverted=inverted))

    assert find_problems(colors, expected_step=round(256 / n)) == []


def test_find_problems_reports_bad_transition() -> None:
    colors = [(0, 0, 0), (64, 64, 0)]

    problems = find_problems(colors, expected_step=64)

    assert len(problems) == 2
    assert 'changed 2 components' in problems[0]


def find_problems(colors: list[RGB], expected_step: int) -> list[str]:
    problems = []
    for index, current in enumerate(colors):
        next_index = (index + 1) % len(colors)
        next_color = colors[next_index]
        if problem := describe_problem(
            index,
            current,
            next_index,
            next_color,
            expected_step,
        ):
            problems.append(problem)
    return problems


def describe_problem(
    index: int,
    current: RGB,
    next_index: int,
    next_color: RGB,
    expected_step: int,
) -> str | None:
    deltas = tuple(b - a for a, b in zip(current, next_color, strict=True))
    changed = [i for i, delta in enumerate(deltas) if delta]
    if len(changed) != 1:
        return (
            f'{index} -> {next_index}: {current} -> {next_color}; '
            f'changed {len(changed)} components with deltas {deltas}'
        )

    changed_delta = abs(deltas[changed[0]])
    if changed_delta != expected_step:
        return (
            f'{index} -> {next_index}: {current} -> {next_color}; '
            f'changed component {changed[0]} by {changed_delta}, '
            f'expected {expected_step}; deltas {deltas}'
        )
    return None

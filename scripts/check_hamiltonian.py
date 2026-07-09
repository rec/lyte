#!/usr/bin/env python3
"""Check Hamiltonian RGB sequence adjacency without connecting to lights."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte.hamiltonian import RGB, hamiltonian_colors


def main() -> int:
    args = parse_args()
    colors = list(
        hamiltonian_colors(
            n=args.n,
            order=args.order,
            inverted=args.inverted,
        )
    )
    problems = list(find_problems(colors, expected_step=round(256 / args.n)))

    if not problems:
        print(f"OK: checked {len(colors)} colors plus wrap-around.")
        return 0

    print(
        "FAILED: "
        f"{len(problems)} non-Hamiltonian RGB transitions in {len(colors)} colors."
    )
    for problem in problems[: args.limit]:
        print(problem)
    if len(problems) > args.limit:
        print(f"... {len(problems) - args.limit} more not shown")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--order", default="rgb")
    parser.add_argument("--inverted", default="")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def find_problems(colors: list[RGB], expected_step: int) -> list[str]:
    problems = []
    for index, current in enumerate(colors):
        next_index = (index + 1) % len(colors)
        next_color = colors[next_index]
        problem = describe_problem(
            index,
            current,
            next_index,
            next_color,
            expected_step,
        )
        if problem:
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
            f"{index} -> {next_index}: {current} -> {next_color}; "
            f"changed {len(changed)} components with deltas {deltas}"
        )

    changed_delta = abs(deltas[changed[0]])
    if changed_delta != expected_step:
        return (
            f"{index} -> {next_index}: {current} -> {next_color}; "
            f"changed component {changed[0]} by {changed_delta}, "
            f"expected {expected_step}; deltas {deltas}"
        )
    return None


if __name__ == "__main__":
    raise SystemExit(main())

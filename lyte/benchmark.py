"""Offline rendering benchmark, excluding encoding and device delivery."""

from pathlib import Path
from typing import Annotated

import tyro
from pydantic import BaseModel, Field

from . import show
from .metrics import RenderCost


class BenchmarkConfig(BaseModel, frozen=True):
    selector: Annotated[str, tyro.conf.Positional]
    library_config: Path | None = None
    light_output: str = 'light'
    duration: float = Field(default=10, gt=0, allow_inf_nan=False)
    parameters: dict[str, float] = Field(default_factory=dict)


def benchmark(config: BenchmarkConfig) -> RenderCost:
    prepared = show.prepare_animation(
        show.LightProgramSpec(
            selector=config.selector,
            output=config.light_output,
            parameters=config.parameters,
        ),
        config.library_config,
    )
    for _ in range(max(1, round(prepared.fps * config.duration))):
        prepared.render()
    return prepared.timing


def run_benchmark(config: BenchmarkConfig) -> int:
    print(benchmark(config).model_dump_json(indent=2))
    return 0

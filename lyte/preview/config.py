from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import tyro
from pydantic import BaseModel, Field


class PreviewConfig(BaseModel, frozen=True):
    selector: Annotated[str | None, tyro.conf.Positional] = None
    output: Path | None = None
    library_config: Path | None = None
    light_output: str = 'light'
    parameters: dict[str, float] = Field(default_factory=dict)
    family: str | None = None
    open: bool = False
    name: str | None = None
    led_size: float = 1.0
    plane: Literal['xy', 'xz', 'yz'] = 'xy'
    zoom: float = Field(default=1, gt=0, allow_inf_nan=False)
    background: str = Field(default='#050506', pattern=r'^#[0-9a-fA-F]{6}$')
    duration: float = 10.0

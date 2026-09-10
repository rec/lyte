from __future__ import annotations

from pathlib import Path
from typing import Annotated

import tyro
from pydantic import BaseModel, Field


class PreviewConfig(BaseModel, frozen=True):
    selector: Annotated[str | None, tyro.conf.Positional] = None
    output: Annotated[Path | None, tyro.conf.Positional] = None
    library_config: Path | None = None
    light_output: str = 'light'
    parameters: dict[str, float] = Field(default_factory=dict)
    family: str | None = None
    open: bool = False
    name: str | None = None
    led_size: float = 1.0
    duration: float = 10.0

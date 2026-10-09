"""Shared reccy unit parsing for time and frame-rate CLI arguments."""

from typing import Annotated

from reccy.configuration import units
from reccy.configuration.tyro import unit_spec

Seconds = Annotated[units.Seconds, unit_spec(units.Seconds, 'SECONDS')]
FramesPerSecond = Annotated[
    units.FramesPerSecond, unit_spec(units.FramesPerSecond, 'FPS')
]

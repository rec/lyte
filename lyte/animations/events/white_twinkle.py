from __future__ import annotations

from ..colors import RGB
from .twinkle import Twinkle


class WhiteTwinkle(Twinkle, frozen=True):
    colors: tuple[RGB, ...] = ((255, 255, 255),)
    density: int = 80

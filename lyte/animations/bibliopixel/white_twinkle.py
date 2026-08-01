from __future__ import annotations

from ..util import RGB
from .twinkle import Twinkle


class WhiteTwinkle(Twinkle):
    colors: tuple[RGB, ...] = ((255, 255, 255),)
    density: int = 80

"""Evolve a one-dimensional elementary cellular automaton with fading history.

Recent cell activity maps to a palette rather than only binary on/off values.
Ufor defines rule, initial density, generation rate, history decay, boundary
mode, palette, speed and seed.
"""

from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class CellularAutomatonState(State):
    cells: NDArray[np.bool_]
    history: NDArray[np.float32]
    generation_credit: float = 0


class CellularAutomaton(effects.CellularAutomaton, Animation[CellularAutomatonState]):
    family: ClassVar[Family] = Family.SIMULATIONS

    def initial_state(self, device: Device) -> CellularAutomatonState:
        generator = np.random.default_rng(self.seed)
        cells = generator.random(device.led_count) < self.initial_density
        if not cells.any():
            cells[device.led_count // 2] = True
        return CellularAutomatonState(
            cells=cells,
            history=cells.astype(np.float32),
        )

    def render(
        self, device: Device, state: CellularAutomatonState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.generation_credit += self.generation_rate * dt
        while state.generation_credit >= 1:
            left = np.roll(state.cells, 1)
            right = np.roll(state.cells, -1)
            if self.boundary_mode == 'bounded':
                left[0] = False
                right[-1] = False
            neighbourhood = (
                left.astype(np.uint8) * 4
                + state.cells.astype(np.uint8) * 2
                + right.astype(np.uint8)
            )
            state.cells = ((self.rule >> neighbourhood) & 1).astype(np.bool_)
            state.history *= math.exp(-self.history_decay / self.generation_rate)
            state.history[state.cells] = 1
            state.generation_credit -= 1
        state.frame += 1
        return numerical.map_palette(state.history, self.palette)

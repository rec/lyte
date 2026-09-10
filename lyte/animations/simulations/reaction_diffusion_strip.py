from __future__ import annotations

import random
from typing import ClassVar, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ...animation import Animation, Device, Family, State
from .. import numerical
from ..colors import RGB


class ReactionDiffusionStripState(State):
    activator: NDArray[np.float32]
    inhibitor: NDArray[np.float32]
    step_credit: float = 0


class ReactionDiffusionStrip(Animation[ReactionDiffusionStripState], frozen=True):
    family: ClassVar[Family] = Family.SIMULATIONS

    palette: list[RGB] = Field(default_factory=lambda: list(numerical.REACTION_PALETTE))
    activator_diffusion: float = Field(default=0.16, gt=0)
    inhibitor_diffusion: float = Field(default=0.08, gt=0)
    feed_rate: float = Field(default=0.035, gt=0)
    kill_rate: float = Field(default=0.06, gt=0)
    steps_per_second: float = Field(default=80.0, gt=0)
    boundary_mode: Literal['bounded', 'ring'] = 'ring'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_reaction_diffusion_strip(self) -> ReactionDiffusionStrip:
        numerical.validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> ReactionDiffusionStripState:
        generator = random.Random(self.seed)
        activator = np.ones(device.led_count, dtype=np.float32)
        inhibitor = np.zeros(device.led_count, dtype=np.float32)
        patch_width = max(1, device.led_count // 16)
        for _ in range(max(1, device.led_count // 80)):
            center = generator.randrange(device.led_count)
            indexes = np.arange(center - patch_width, center + patch_width + 1)
            if self.boundary_mode == 'ring':
                indexes %= device.led_count
            else:
                indexes = indexes[(indexes >= 0) & (indexes < device.led_count)]
            activator[indexes] = 0.5
            inhibitor[indexes] = 0.25 + np.array(
                [generator.random() * 0.1 for _ in indexes], dtype=np.float32
            )
        return ReactionDiffusionStripState(
            activator=activator,
            inhibitor=inhibitor,
        )

    def render(
        self, device: Device, state: ReactionDiffusionStripState
    ) -> NDArray[np.float32]:
        state.step_credit += self.steps_per_second * self.speed / state.fps
        step_count = int(state.step_credit)
        state.step_credit -= step_count
        for _ in range(step_count):
            activator_laplacian = numerical.laplacian(
                state.activator, self.boundary_mode
            )
            inhibitor_laplacian = numerical.laplacian(
                state.inhibitor, self.boundary_mode
            )
            reaction = state.activator * state.inhibitor * state.inhibitor
            state.activator += (
                self.activator_diffusion * activator_laplacian
                - reaction
                + self.feed_rate * (1 - state.activator)
            )
            state.inhibitor += (
                self.inhibitor_diffusion * inhibitor_laplacian
                + reaction
                - (self.kill_rate + self.feed_rate) * state.inhibitor
            )
            np.clip(state.activator, 0, 1, out=state.activator)
            np.clip(state.inhibitor, 0, 1, out=state.inhibitor)
        state.frame += 1
        return numerical.map_palette(np.clip(state.inhibitor * 2.5, 0, 1), self.palette)

"""Move colored particles that reflect at the ends and exchange velocity on contact.

Collision flashes and fading trails expose their paths. Ufor defines particle
count, radius, trail decay, collision flash, palette, speed and seed;
initial positions and velocities are seeded.
"""

from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class CollidingParticlesState(State):
    positions: list[float]
    velocities: list[float]
    color_indexes: list[int]
    pixels: NDArray[np.float32]


class CollidingParticles(
    effects.CollidingParticles, Animation[CollidingParticlesState]
):
    family: ClassVar[Family] = Family.SIMULATIONS

    def initial_state(self, device: Device) -> CollidingParticlesState:
        generator = random.Random(self.seed)
        return CollidingParticlesState(
            positions=[
                generator.uniform(0, device.led_count - 1)
                for _ in range(self.particle_count)
            ],
            velocities=[
                generator.choice((-1, 1)) * generator.uniform(4, 10)
                for _ in range(self.particle_count)
            ],
            color_indexes=[
                generator.randrange(len(self.palette))
                for _ in range(self.particle_count)
            ],
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
        )

    def render(
        self, device: Device, state: CollidingParticlesState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.pixels *= math.exp(-self.trail_decay * dt)
        if device.led_count == 1:
            state.positions = [0.0 for _ in state.positions]
            state.velocities = [0.0 for _ in state.velocities]
        for i in range(len(state.positions)):
            state.positions[i] += state.velocities[i] * dt
            if state.positions[i] < 0:
                state.positions[i] = -state.positions[i]
                state.velocities[i] = abs(state.velocities[i])
            elif state.positions[i] > device.led_count - 1:
                state.positions[i] = 2 * (device.led_count - 1) - state.positions[i]
                state.velocities[i] = -abs(state.velocities[i])
        for i in range(len(state.positions)):
            for j in range(i + 1, len(state.positions)):
                separation = state.positions[i] - state.positions[j]
                relative_velocity = state.velocities[i] - state.velocities[j]
                if (
                    abs(separation) <= self.radius
                    and separation * relative_velocity < 0
                ):
                    state.velocities[i], state.velocities[j] = (
                        state.velocities[j],
                        state.velocities[i],
                    )
                    center = round((state.positions[i] + state.positions[j]) / 2)
                    if 0 <= center < device.led_count:
                        state.pixels[center] = np.maximum(
                            state.pixels[center], self.collision_flash
                        )
        indexes = np.arange(device.led_count, dtype=np.float32)
        colors = numerical.palette_array(self.palette)
        for position, color_index in zip(
            state.positions, state.color_indexes, strict=True
        ):
            glow = np.exp(-0.5 * ((indexes - position) / self.radius) ** 2)
            state.pixels = np.maximum(state.pixels, glow[:, None] * colors[color_index])
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))

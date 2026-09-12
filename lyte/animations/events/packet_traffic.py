"""Send structured groups of pulses with headers, payloads and gaps.

Successful packets can produce acknowledgements traveling in the opposite
direction. Ufor defines direction, packet rate, length range, error rate,
palette, speed and seed.
"""

from __future__ import annotations

import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class PacketTrafficState(State):
    positions: list[float]
    lengths: list[int]
    directions: list[int]
    color_indexes: list[int]
    is_acknowledgement: list[bool]
    generator: random.Random
    spawn_credit: float = 0


class PacketTraffic(effects.PacketTraffic, Animation[PacketTrafficState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> PacketTrafficState:
        generator = random.Random(self.seed)
        direction = numerical.packet_direction(self.direction, generator)
        length = generator.randint(self.minimum_length, self.maximum_length)
        position = -1.0 if direction > 0 else float(device.led_count)
        return PacketTrafficState(
            positions=[position],
            lengths=[length],
            directions=[direction],
            color_indexes=[generator.randrange(len(self.palette))],
            is_acknowledgement=[False],
            generator=generator,
        )

    def render(self, device: Device, state: PacketTrafficState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        colors = numerical.palette_array(self.palette)
        keep: list[int] = []
        acknowledgements: list[tuple[float, int]] = []
        for i, (
            position,
            length,
            direction,
            color_index,
            is_acknowledgement,
        ) in enumerate(
            zip(
                state.positions,
                state.lengths,
                state.directions,
                state.color_indexes,
                state.is_acknowledgement,
                strict=True,
            )
        ):
            position += direction * 10 * dt
            state.positions[i] = position
            for offset in range(length):
                if offset > 0 and offset % 4 == 3:
                    continue
                index = round(position - direction * offset)
                if 0 <= index < device.led_count:
                    level = 1.0 if offset == 0 else 0.35 + 0.45 * (offset % 2)
                    frame[index] = np.maximum(frame[index], colors[color_index] * level)
            exited = (
                position - direction * length > device.led_count
                if direction > 0
                else position - direction * length < 0
            )
            if not exited:
                keep.append(i)
            elif not is_acknowledgement and state.generator.random() >= self.error_rate:
                acknowledgement_direction = -direction
                acknowledgement_position = (
                    float(device.led_count) if acknowledgement_direction < 0 else -1.0
                )
                acknowledgements.append(
                    (acknowledgement_position, acknowledgement_direction)
                )
        state.positions = [state.positions[i] for i in keep]
        state.lengths = [state.lengths[i] for i in keep]
        state.directions = [state.directions[i] for i in keep]
        state.color_indexes = [state.color_indexes[i] for i in keep]
        state.is_acknowledgement = [state.is_acknowledgement[i] for i in keep]
        for position, direction in acknowledgements:
            state.positions.append(position)
            state.lengths.append(2)
            state.directions.append(direction)
            state.color_indexes.append(0)
            state.is_acknowledgement.append(True)
        state.spawn_credit += self.packet_rate * dt
        while state.spawn_credit >= 1:
            state.spawn_credit -= 1
            direction = numerical.packet_direction(self.direction, state.generator)
            state.positions.append(-1.0 if direction > 0 else float(device.led_count))
            state.lengths.append(
                state.generator.randint(self.minimum_length, self.maximum_length)
            )
            state.directions.append(direction)
            state.color_indexes.append(state.generator.randrange(len(self.palette)))
            state.is_acknowledgement.append(False)
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))

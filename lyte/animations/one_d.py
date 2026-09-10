"""Procedural animations for one-dimensional LED strings."""

from __future__ import annotations

import math
import random
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ..animation import Animation, Device, State, float_color_from_rgb
from .colors import RGB
from .validators import validate_rgb


class FireAndEmbersState(State):
    heat: NDArray[np.float32]
    generator: random.Random


class FireAndEmbers(Animation[FireAndEmbersState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(FIRE_PALETTE))
    cooling: float = Field(default=1.4, gt=0)
    diffusion: float = Field(default=4.0, ge=0)
    spark_rate: float = Field(default=12.0, ge=0)
    wind: float = 3.0
    origin: Literal['start', 'end'] = 'start'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_fire_and_embers(self) -> FireAndEmbers:
        _validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> FireAndEmbersState:
        return FireAndEmbersState(
            heat=np.zeros(device.led_count, dtype=np.float32),
            generator=random.Random(self.seed),
        )

    def render(self, device: Device, state: FireAndEmbersState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.heat *= math.exp(-self.cooling * dt)
        padded = np.pad(state.heat, 1, mode='edge')
        neighbours = (padded[:-2] + padded[2:]) / 2
        state.heat += min(0.5, self.diffusion * dt) * (neighbours - state.heat)
        direction = 1 if self.origin == 'start' else -1
        if self.wind:
            indexes = np.arange(device.led_count, dtype=np.float32)
            source = indexes - direction * self.wind * dt
            state.heat = np.interp(
                source,
                indexes,
                state.heat,
                left=0.0,
                right=0.0,
            ).astype(np.float32)
        spark_count = int(self.spark_rate * dt)
        if state.generator.random() < self.spark_rate * dt - spark_count:
            spark_count += 1
        for _ in range(spark_count):
            distance = state.generator.randrange(max(1, min(4, device.led_count)))
            index = distance if direction > 0 else device.led_count - 1 - distance
            state.heat[index] = min(
                1.0, state.heat[index] + state.generator.uniform(0.6, 1.0)
            )
        state.frame += 1
        return _map_palette(state.heat, self.palette)


class AuroraState(State):
    phases: list[float]
    rates: list[float]


class Aurora(Animation[AuroraState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(AURORA_PALETTE))
    band_count: int = Field(default=4, gt=0)
    softness: float = Field(default=0.16, gt=0)
    intensity: float = Field(default=0.8, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_aurora(self) -> Aurora:
        _validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> AuroraState:
        generator = random.Random(self.seed)
        return AuroraState(
            phases=[generator.uniform(0, math.tau) for _ in range(self.band_count)],
            rates=[generator.uniform(0.12, 0.35) for _ in range(self.band_count)],
        )

    def render(self, device: Device, state: AuroraState) -> NDArray[np.float32]:
        x = np.linspace(0, 1, device.led_count, dtype=np.float32)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        colors = _palette_array(self.palette)
        for i, phase in enumerate(state.phases):
            center = 0.5 + 0.45 * math.sin(phase + 0.37 * math.sin(phase * 0.31))
            width = self.softness * (0.75 + 0.5 * math.sin(phase * 0.43) ** 2)
            band = np.exp(-0.5 * ((x - center) / width) ** 2).astype(np.float32)
            frame += band[:, None] * colors[i % len(colors)]
            state.phases[i] += state.rates[i] * self.speed / state.fps
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame * self.intensity, 0, 1))


class OceanCurrentState(State):
    phases: list[float]
    rates: list[float]
    wavelengths: list[float]
    crests: NDArray[np.float32]
    generator: random.Random


class OceanCurrent(Animation[OceanCurrentState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(OCEAN_PALETTE))
    wave_count: int = Field(default=3, gt=0)
    crest_rate: float = Field(default=0.8, ge=0)
    turbulence: float = Field(default=0.2, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_ocean_current(self) -> OceanCurrent:
        _validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> OceanCurrentState:
        generator = random.Random(self.seed)
        return OceanCurrentState(
            phases=[generator.uniform(0, math.tau) for _ in range(self.wave_count)],
            rates=[generator.uniform(-0.8, 0.8) for _ in range(self.wave_count)],
            wavelengths=[generator.uniform(0.2, 0.8) for _ in range(self.wave_count)],
            crests=np.zeros(device.led_count, dtype=np.float32),
            generator=generator,
        )

    def render(self, device: Device, state: OceanCurrentState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        x = np.linspace(0, 1, device.led_count, dtype=np.float32)
        field = np.zeros(device.led_count, dtype=np.float32)
        for i in range(self.wave_count):
            field += np.sin(math.tau * x / state.wavelengths[i] + state.phases[i])
            state.phases[i] += state.rates[i] * dt
        field = 0.45 + 0.25 * field / self.wave_count
        state.crests *= math.exp(-4 * dt)
        if state.generator.random() < min(1.0, self.crest_rate * dt):
            center = state.generator.randrange(device.led_count)
            distance = np.arange(device.led_count, dtype=np.float32) - center
            width = max(1.0, device.led_count * 0.03)
            state.crests += np.exp(-0.5 * (distance / width) ** 2).astype(np.float32)
        noise = np.array(
            [state.generator.uniform(-1, 1) for _ in range(device.led_count)],
            dtype=np.float32,
        )
        values = field + state.crests * 0.45 + noise * self.turbulence * 0.05
        state.frame += 1
        return _map_palette(values, self.palette)


class Interference(Animation[State], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(INTERFERENCE_PALETTE))
    wavelengths: list[float] = Field(default_factory=lambda: [13.0, 23.0, 37.0])
    rates: list[float] = Field(default_factory=lambda: [1.0, -0.63, 0.37])
    phase_offsets: list[float] = Field(default_factory=lambda: [0.0, 1.7, 3.1])
    contrast: float = Field(default=1.4, gt=0)
    speed: float = Field(default=1.0, ge=0)

    @model_validator(mode='after')
    def validate_interference(self) -> Interference:
        _validate_palette(self.palette)
        if not self.wavelengths:
            raise ValueError('wavelengths must not be empty')
        if len(self.wavelengths) != len(self.rates) or len(self.rates) != len(
            self.phase_offsets
        ):
            raise ValueError(
                'wavelengths, rates, and phase_offsets must have equal size'
            )
        if any(v <= 0 for v in self.wavelengths):
            raise ValueError('wavelengths must be greater than zero')
        return self

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        indexes = np.arange(device.led_count, dtype=np.float32)
        elapsed = state.frame * self.speed / state.fps
        field = np.zeros(device.led_count, dtype=np.float32)
        for wavelength, rate, offset in zip(
            self.wavelengths, self.rates, self.phase_offsets, strict=True
        ):
            effective_wavelength = wavelength * (
                1 + 0.08 * math.sin(elapsed * 0.13 + offset)
            )
            field += np.sin(
                math.tau * indexes / effective_wavelength + elapsed * rate + offset
            )
        values = np.clip(0.5 + field / (2 * len(self.wavelengths)), 0, 1)
        values = np.clip(0.5 + (values - 0.5) * self.contrast, 0, 1)
        state.frame += 1
        return _map_palette(values, self.palette)


class PaletteConveyor(Animation[State], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(CONVEYOR_PALETTE))
    stop_spacing: float = Field(default=8.0, gt=0)
    speed: float = Field(default=1.0, ge=0)
    reverse: bool = False
    interpolation: Literal['linear', 'smooth'] = 'smooth'

    @model_validator(mode='after')
    def validate_palette_conveyor(self) -> PaletteConveyor:
        _validate_palette(self.palette)
        return self

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        direction = -1 if self.reverse else 1
        offset = direction * state.frame * self.speed / state.fps
        values = np.arange(device.led_count, dtype=np.float32) / self.stop_spacing
        values += offset
        if self.interpolation == 'smooth':
            integral = np.floor(values)
            fraction = values - integral
            values = integral + fraction * fraction * (3 - 2 * fraction)
        state.frame += 1
        return _map_palette(values, self.palette, cyclic=True)


class ConfettiWithDecayState(State):
    pixels: NDArray[np.float32]
    generator: random.Random
    spawn_credit: float = 0


class ConfettiWithDecay(Animation[ConfettiWithDecayState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(CONFETTI_PALETTE))
    spawn_rate: float = Field(default=8.0, ge=0)
    decay: float = Field(default=2.5, gt=0)
    width: int = Field(default=1, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_confetti_with_decay(self) -> ConfettiWithDecay:
        _validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> ConfettiWithDecayState:
        return ConfettiWithDecayState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
            generator=random.Random(self.seed),
            spawn_credit=1,
        )

    def render(
        self, device: Device, state: ConfettiWithDecayState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.pixels *= math.exp(-self.decay * dt)
        state.spawn_credit += self.spawn_rate * dt
        spawn_count = int(state.spawn_credit)
        state.spawn_credit -= spawn_count
        for _ in range(spawn_count):
            index = state.generator.randrange(device.led_count)
            color = float_color_from_rgb(state.generator.choice(self.palette))
            state.pixels[index : min(device.led_count, index + self.width)] = color
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))


class LightningStormState(State):
    pixels: NDArray[np.float32]
    generator: random.Random
    wait: float = 0
    burst_remaining: int = 0


class LightningStorm(Animation[LightningStormState], frozen=True):
    color: RGB = (200, 220, 255)
    flash_rate: float = Field(default=0.35, gt=0)
    maximum_burst: int = Field(default=4, gt=0)
    branch_width: float = Field(default=5.0, gt=0)
    afterglow: float = Field(default=8.0, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_lightning_storm(self) -> LightningStorm:
        validate_rgb(self.color)
        return self

    def initial_state(self, device: Device) -> LightningStormState:
        return LightningStormState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
            generator=random.Random(self.seed),
        )

    def render(self, device: Device, state: LightningStormState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.pixels *= math.exp(-self.afterglow * dt)
        state.wait -= dt
        if state.wait <= 0:
            center = state.generator.randrange(device.led_count)
            distance = np.abs(np.arange(device.led_count, dtype=np.float32) - center)
            flash = np.exp(-distance / self.branch_width).astype(np.float32)
            color = np.array(float_color_from_rgb(self.color), dtype=np.float32)
            state.pixels = np.maximum(state.pixels, flash[:, None] * color)
            if state.burst_remaining <= 0:
                state.burst_remaining = state.generator.randrange(self.maximum_burst)
            if state.burst_remaining:
                state.burst_remaining -= 1
                state.wait = state.generator.uniform(0.04, 0.16)
            else:
                state.wait = state.generator.expovariate(self.flash_rate)
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))


class CandleBankState(State):
    levels: list[float]
    targets: list[float]
    generator: random.Random


class CandleBank(Animation[CandleBankState], frozen=True):
    color: RGB = (255, 120, 30)
    zone_size: int = Field(default=8, gt=0)
    base_level: float = Field(default=0.55, ge=0, le=1)
    flicker: float = Field(default=0.18, ge=0, le=1)
    flare_rate: float = Field(default=0.3, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_candle_bank(self) -> CandleBank:
        validate_rgb(self.color)
        return self

    def initial_state(self, device: Device) -> CandleBankState:
        generator = random.Random(self.seed)
        zone_count = math.ceil(device.led_count / self.zone_size)
        levels = [self.base_level for _ in range(zone_count)]
        return CandleBankState(levels=levels, targets=list(levels), generator=generator)

    def render(self, device: Device, state: CandleBankState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        color = np.array(float_color_from_rgb(self.color), dtype=np.float32)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        for i in range(len(state.levels)):
            if state.generator.random() < min(1.0, self.flare_rate * dt):
                state.targets[i] = min(1.0, self.base_level + self.flicker * 2)
            elif state.generator.random() < min(1.0, 5 * dt):
                variation = state.generator.uniform(-self.flicker, self.flicker)
                state.targets[i] = min(1.0, max(0.0, self.base_level + variation))
            state.levels[i] += (state.targets[i] - state.levels[i]) * min(1.0, 8 * dt)
            start = i * self.zone_size
            frame[start : min(device.led_count, start + self.zone_size)] = (
                color * state.levels[i]
            )
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))


class CollidingParticlesState(State):
    positions: list[float]
    velocities: list[float]
    color_indexes: list[int]
    pixels: NDArray[np.float32]


class CollidingParticles(Animation[CollidingParticlesState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(PARTICLE_PALETTE))
    particle_count: int = Field(default=5, gt=0)
    radius: float = Field(default=1.5, gt=0)
    trail_decay: float = Field(default=4.0, gt=0)
    collision_flash: float = Field(default=0.7, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_colliding_particles(self) -> CollidingParticles:
        _validate_palette(self.palette)
        return self

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
        colors = _palette_array(self.palette)
        for position, color_index in zip(
            state.positions, state.color_indexes, strict=True
        ):
            glow = np.exp(-0.5 * ((indexes - position) / self.radius) ** 2)
            state.pixels = np.maximum(state.pixels, glow[:, None] * colors[color_index])
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))


class ExpandingRipplesState(State):
    origins: list[float]
    ages: list[float]
    color_indexes: list[int]
    generator: random.Random
    spawn_credit: float = 0


class ExpandingRipples(Animation[ExpandingRipplesState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(RIPPLE_PALETTE))
    origins: list[float] = Field(default_factory=lambda: [0.5])
    event_rate: float = Field(default=0.35, ge=0)
    propagation_speed: float = Field(default=12.0, gt=0)
    width: float = Field(default=1.8, gt=0)
    decay: float = Field(default=0.7, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_expanding_ripples(self) -> ExpandingRipples:
        _validate_palette(self.palette)
        if not self.origins:
            raise ValueError('origins must not be empty')
        if any(v < 0 or v > 1 for v in self.origins):
            raise ValueError('origins must be between zero and one')
        return self

    def initial_state(self, device: Device) -> ExpandingRipplesState:
        generator = random.Random(self.seed)
        return ExpandingRipplesState(
            origins=[self.origins[0] * (device.led_count - 1)],
            ages=[0],
            color_indexes=[generator.randrange(len(self.palette))],
            generator=generator,
        )

    def render(
        self, device: Device, state: ExpandingRipplesState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        indexes = np.arange(device.led_count, dtype=np.float32)
        colors = _palette_array(self.palette)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        keep: list[int] = []
        for i, (origin, age, color_index) in enumerate(
            zip(state.origins, state.ages, state.color_indexes, strict=True)
        ):
            radius = age * self.propagation_speed
            distance = np.abs(indexes - origin)
            wave = np.exp(-0.5 * ((distance - radius) / self.width) ** 2)
            amplitude = math.exp(-self.decay * age)
            frame += wave[:, None] * colors[color_index] * amplitude
            state.ages[i] += dt
            if radius <= device.led_count + self.width and amplitude > 0.01:
                keep.append(i)
        state.origins = [state.origins[i] for i in keep]
        state.ages = [state.ages[i] for i in keep]
        state.color_indexes = [state.color_indexes[i] for i in keep]
        state.spawn_credit += self.event_rate * dt
        while state.spawn_credit >= 1:
            state.spawn_credit -= 1
            origin = state.generator.choice(self.origins) * (device.led_count - 1)
            state.origins.append(origin)
            state.ages.append(0)
            state.color_indexes.append(state.generator.randrange(len(self.palette)))
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))


class CellularAutomatonState(State):
    cells: NDArray[np.bool_]
    history: NDArray[np.float32]
    generation_credit: float = 0


class CellularAutomaton(Animation[CellularAutomatonState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(CELLULAR_PALETTE))
    rule: int = Field(default=110, ge=0, le=255)
    initial_density: float = Field(default=0.25, ge=0, le=1)
    generation_rate: float = Field(default=10.0, gt=0)
    history_decay: float = Field(default=1.8, gt=0)
    boundary_mode: Literal['bounded', 'ring'] = 'ring'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_cellular_automaton(self) -> CellularAutomaton:
        _validate_palette(self.palette)
        return self

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
        return _map_palette(state.history, self.palette)


class ReactionDiffusionStripState(State):
    activator: NDArray[np.float32]
    inhibitor: NDArray[np.float32]
    step_credit: float = 0


class ReactionDiffusionStrip(Animation[ReactionDiffusionStripState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(REACTION_PALETTE))
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
        _validate_palette(self.palette)
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
            activator_laplacian = _laplacian(state.activator, self.boundary_mode)
            inhibitor_laplacian = _laplacian(state.inhibitor, self.boundary_mode)
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
        return _map_palette(np.clip(state.inhibitor * 2.5, 0, 1), self.palette)


class PacketTrafficState(State):
    positions: list[float]
    lengths: list[int]
    directions: list[int]
    color_indexes: list[int]
    is_acknowledgement: list[bool]
    generator: random.Random
    spawn_credit: float = 0


class PacketTraffic(Animation[PacketTrafficState], frozen=True):
    palette: list[RGB] = Field(default_factory=lambda: list(PACKET_PALETTE))
    direction: Literal['forward', 'reverse', 'both'] = 'both'
    packet_rate: float = Field(default=1.2, ge=0)
    minimum_length: int = Field(default=4, gt=1)
    maximum_length: int = Field(default=12, gt=1)
    error_rate: float = Field(default=0.15, ge=0, le=1)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_packet_traffic(self) -> PacketTraffic:
        _validate_palette(self.palette)
        if self.maximum_length < self.minimum_length:
            raise ValueError('maximum_length must be at least minimum_length')
        return self

    def initial_state(self, device: Device) -> PacketTrafficState:
        generator = random.Random(self.seed)
        direction = _packet_direction(self.direction, generator)
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
        colors = _palette_array(self.palette)
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
            direction = _packet_direction(self.direction, state.generator)
            state.positions.append(-1.0 if direction > 0 else float(device.led_count))
            state.lengths.append(
                state.generator.randint(self.minimum_length, self.maximum_length)
            )
            state.directions.append(direction)
            state.color_indexes.append(state.generator.randrange(len(self.palette)))
            state.is_acknowledgement.append(False)
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))


def _validate_palette(palette: list[RGB]) -> None:
    if not palette:
        raise ValueError('palette must not be empty')
    for color in palette:
        validate_rgb(color)


def _palette_array(palette: list[RGB]) -> NDArray[np.float32]:
    return np.array([float_color_from_rgb(c) for c in palette], dtype=np.float32)


def _map_palette(
    values: NDArray[np.float32], palette: list[RGB], cyclic: bool = False
) -> NDArray[np.float32]:
    colors = _palette_array(palette)
    if len(colors) == 1:
        return np.ascontiguousarray(np.clip(values, 0, 1)[:, None] * colors[0])
    if cyclic:
        scaled = np.mod(values, len(colors))
        lower = np.floor(scaled).astype(np.intp)
        upper = (lower + 1) % len(colors)
        fraction = scaled - lower
    else:
        scaled = np.clip(values, 0, 1) * (len(colors) - 1)
        lower = np.floor(scaled).astype(np.intp)
        upper = np.minimum(lower + 1, len(colors) - 1)
        fraction = scaled - lower
    frame = colors[lower] * (1 - fraction[:, None])
    frame += colors[upper] * fraction[:, None]
    return np.ascontiguousarray(np.clip(frame, 0, 1).astype(np.float32))


def _laplacian(
    values: NDArray[np.float32], boundary_mode: Literal['bounded', 'ring']
) -> NDArray[np.float32]:
    left = np.roll(values, 1)
    right = np.roll(values, -1)
    if boundary_mode == 'bounded':
        left[0] = values[0]
        right[-1] = values[-1]
    return left + right - 2 * values


def _packet_direction(
    direction: Literal['forward', 'reverse', 'both'], generator: random.Random
) -> int:
    if direction == 'forward':
        return 1
    if direction == 'reverse':
        return -1
    return generator.choice((-1, 1))


FIRE_PALETTE: tuple[RGB, ...] = (
    (0, 0, 0),
    (120, 0, 0),
    (255, 50, 0),
    (255, 190, 20),
    (255, 255, 220),
)
AURORA_PALETTE: tuple[RGB, ...] = (
    (20, 220, 120),
    (30, 100, 255),
    (180, 40, 255),
    (10, 255, 210),
)
OCEAN_PALETTE: tuple[RGB, ...] = (
    (0, 5, 20),
    (0, 50, 120),
    (0, 170, 210),
    (180, 255, 255),
)
INTERFERENCE_PALETTE: tuple[RGB, ...] = (
    (5, 0, 20),
    (200, 20, 120),
    (30, 220, 255),
)
CONVEYOR_PALETTE: tuple[RGB, ...] = (
    (255, 0, 80),
    (255, 180, 0),
    (0, 220, 140),
    (30, 80, 255),
)
CONFETTI_PALETTE: tuple[RGB, ...] = (
    (255, 40, 80),
    (255, 220, 40),
    (30, 220, 180),
    (80, 100, 255),
)
PARTICLE_PALETTE: tuple[RGB, ...] = (
    (255, 50, 30),
    (255, 220, 40),
    (30, 220, 180),
    (80, 100, 255),
    (220, 50, 255),
)
RIPPLE_PALETTE: tuple[RGB, ...] = (
    (40, 120, 255),
    (20, 255, 180),
    (220, 80, 255),
)
CELLULAR_PALETTE: tuple[RGB, ...] = (
    (0, 0, 0),
    (20, 40, 120),
    (40, 220, 180),
    (255, 240, 120),
)
REACTION_PALETTE: tuple[RGB, ...] = (
    (5, 0, 20),
    (40, 20, 130),
    (20, 190, 190),
    (240, 230, 120),
)
PACKET_PALETTE: tuple[RGB, ...] = (
    (50, 220, 255),
    (255, 70, 130),
    (255, 210, 50),
)

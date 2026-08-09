from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Protocol, cast

import mido
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, SkipValidation, model_validator

from . import animation


class MidiInput(Protocol):
    def close(self) -> None: ...

    def poll(self) -> mido.Message | None: ...


class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None

    @model_validator(mode='after')
    def validate_channel(self) -> MidiIn:
        if self.channel is not None and not 0 <= self.channel <= 15:
            raise ValueError('MIDI channel must be between 0 and 15')
        if isinstance(self.device_name, list) and not self.device_name:
            raise ValueError('MIDI device_name list must not be empty')
        return self


def open_input(config: MidiIn) -> MidiInput:
    available_names = list(mido.get_input_names())
    configured_names = (
        [config.device_name]
        if isinstance(config.device_name, str)
        else config.device_name
    )
    if configured_names is None:
        if len(available_names) != 1:
            raise ValueError('Select one MIDI input device')
        name = available_names[0]
    else:
        name = next((n for n in configured_names if n in available_names), None)
        if name is None:
            raise ValueError('Configured MIDI input device is unavailable')
    return cast(MidiInput, mido.open_input(name))


def input_messages(port: MidiInput, config: MidiIn) -> Iterator[mido.Message]:
    poll = port.poll
    while (msg := poll()) is not None:
        if config.channel is None or getattr(msg, 'channel', None) == config.channel:
            yield msg


class Patch[ConfigT: BaseModel, StateT: BaseModel](BaseModel, ABC):
    config: ConfigT
    state: StateT | None = None
    active_note: int | None = None
    breath_control_value: int | None = None

    """
    When playing a note, the WX7 sends

    1. A note on with a positive velocity, then:
    2. A series of breath control messages, then:
    3. Either a note off: a note on with zero velocity, when the player stops blowing
    4. Or a new note on: when the player changes fingering while blowing

    """

    @abstractmethod
    def make_state(self, msg: mido.Message) -> StateT:
        pass

    def receive(self, msg: mido.Message) -> None:
        match msg.type:
            case 'note_on' if msg.velocity:
                self.start_note(msg)
            case 'note_on' | 'note_off':
                self.end_note(msg.note)
            case 'control_change' if self.state is not None and msg.control == 2:
                self.breath_control_value = msg.value
                self.breath_control(msg)
            case 'pitchwheel' if self.state is not None:
                self.pitch_bend(msg)

    def start_note(self, msg: mido.Message) -> None:
        if self.state is not None:
            self.note_off()
        self.state = self.make_state(msg)
        self.active_note = msg.note
        self.breath_control_value = None
        self.note_on(msg)

    def end_note(self, note: int) -> None:
        if self.state is None or self.active_note != note:
            return
        self.note_off()
        self.state = None
        self.active_note = None
        self.breath_control_value = None

    # Classes optionally override the below.
    def note_on(self, msg: mido.Message) -> None:
        pass

    def note_off(self) -> None:
        pass

    def breath_control(self, msg: mido.Message) -> None:
        pass

    def pitch_bend(self, msg: mido.Message) -> None:
        pass

    model_config = ConfigDict(arbitrary_types_allowed=True)


class LightPatch[ConfigT: BaseModel, StateT: BaseModel](Patch[ConfigT, StateT], ABC):
    @abstractmethod
    def render(self, device: animation.Device) -> NDArray[np.float32]:
        pass


class RegionAnimation(BaseModel, frozen=True):
    animation: SkipValidation[animation.Animation]
    start: int
    led_count: int

    @model_validator(mode='after')
    def validate_region(self) -> RegionAnimation:
        if self.start < 0:
            raise ValueError('Region animation start must not be negative')
        if self.led_count <= 0:
            raise ValueError('Region animation led_count must be greater than zero')
        return self

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RegionLightPatchConfig(BaseModel, frozen=True):
    regions: list[RegionAnimation]

    @model_validator(mode='after')
    def validate_regions(self) -> RegionLightPatchConfig:
        if not self.regions:
            raise ValueError('RegionLightPatch requires at least one region')
        return self


class RegionLightPatchState(BaseModel):
    device_led_count: int | None = None
    states: list[SkipValidation[animation.State]] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RegionLightPatch(LightPatch[RegionLightPatchConfig, RegionLightPatchState]):
    def make_state(self, msg: mido.Message) -> RegionLightPatchState:
        return RegionLightPatchState()

    def render(self, device: animation.Device) -> NDArray[np.float32]:
        if (state := self.state) is None:
            return animation.validate_frame(
                device, np.zeros((device.led_count, 3), dtype=np.float32)
            )
        self.ensure_states(device, state)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        for region, child_state in zip(self.config.regions, state.states, strict=True):
            child_device = animation.Device(led_count=region.led_count)
            end = region.start + region.led_count
            frame[region.start : end] = animation.validate_frame(
                child_device, region.animation.render(child_device, child_state)
            )
        return animation.validate_frame(device, frame)

    def ensure_states(
        self, device: animation.Device, state: RegionLightPatchState
    ) -> None:
        if state.device_led_count == device.led_count:
            return
        for region in self.config.regions:
            if region.start + region.led_count > device.led_count:
                raise ValueError('Region animation must fit within device led_count')
        state.states = [
            region.animation.initial_state(animation.Device(led_count=region.led_count))
            for region in self.config.regions
        ]
        state.device_led_count = device.led_count


class BlendLightPatchConfig(BaseModel, frozen=True):
    pass


class BlendLightPatchState(BaseModel):
    pass


class BlendLightPatch(LightPatch[BlendLightPatchConfig, BlendLightPatchState]):
    patches: list[SkipValidation[LightPatch]]

    def make_state(self, msg: mido.Message) -> BlendLightPatchState:
        return BlendLightPatchState()

    def receive(self, msg: mido.Message) -> None:
        super().receive(msg)
        for patch in self.patches:
            patch.receive(msg)

    def render(self, device: animation.Device) -> NDArray[np.float32]:
        return self.blend(device, [patch.render(device) for patch in self.patches])

    def blend(
        self, device: animation.Device, frames: list[NDArray[np.float32]]
    ) -> NDArray[np.float32]:
        return add_light_frames(device, frames)


class WeightedBlendLightPatchConfig(BaseModel, frozen=True):
    weights: list[float]

    @model_validator(mode='after')
    def validate_weights(self) -> WeightedBlendLightPatchConfig:
        if not self.weights:
            raise ValueError('WeightedBlendLightPatch requires at least one weight')
        if any(weight < 0 for weight in self.weights):
            raise ValueError('Blend weights must not be negative')
        return self


class WeightedBlendLightPatchState(BaseModel):
    weights: list[float]


class WeightedBlendLightPatch(
    LightPatch[WeightedBlendLightPatchConfig, WeightedBlendLightPatchState]
):
    patches: list[SkipValidation[LightPatch]]

    @model_validator(mode='after')
    def validate_patches(self) -> WeightedBlendLightPatch:
        if len(self.patches) != len(self.config.weights):
            raise ValueError('Blend weights must match the number of patches')
        return self

    def make_state(self, msg: mido.Message) -> WeightedBlendLightPatchState:
        return WeightedBlendLightPatchState(weights=list(self.config.weights))

    def receive(self, msg: mido.Message) -> None:
        super().receive(msg)
        for patch in self.patches:
            patch.receive(msg)

    def render(self, device: animation.Device) -> NDArray[np.float32]:
        return self.blend(device, [patch.render(device) for patch in self.patches])

    def blend(
        self, device: animation.Device, frames: list[NDArray[np.float32]]
    ) -> NDArray[np.float32]:
        if (state := self.state) is None:
            return animation.validate_frame(
                device, np.zeros((device.led_count, 3), dtype=np.float32)
            )
        if len(state.weights) != len(frames):
            raise ValueError('Blend state weights must match the number of frames')
        total = np.zeros((device.led_count, 3), dtype=np.float32)
        for frame, weight in zip(frames, state.weights, strict=True):
            total += animation.validate_frame(device, frame) * weight
        return animation.validate_frame(device, np.clip(total, 0.0, 1.0))

    def set_weight(self, index: int, value: float) -> None:
        if value < 0:
            raise ValueError('Blend weight must not be negative')
        if (state := self.state) is None:
            raise ValueError('Cannot change a blend weight without an active note')
        state.weights[index] = value


class UnionLightPatchConfig(BaseModel, frozen=True):
    pass


class UnionLightPatchState(BaseModel):
    pass


class UnionLightPatch(Patch[UnionLightPatchConfig, UnionLightPatchState]):
    patches: dict[str, SkipValidation[LightPatch]]

    def make_state(self, msg: mido.Message) -> UnionLightPatchState:
        return UnionLightPatchState()

    def receive(self, msg: mido.Message) -> None:
        for patch in self.patches.values():
            patch.receive(msg)

    def render(
        self, devices: dict[str, animation.Device]
    ) -> dict[str, NDArray[np.float32]]:
        if self.patches.keys() != devices.keys():
            raise ValueError('Union patch names must match device names')
        frames = {}
        for name, patch in self.patches.items():
            device = devices[name]
            frames[name] = animation.validate_frame(device, patch.render(device))
        return frames


class DeviceSegment(BaseModel, frozen=True):
    device: animation.Device
    start: int
    led_count: int

    @model_validator(mode='after')
    def validate_segment(self) -> DeviceSegment:
        if self.start < 0:
            raise ValueError('Device segment start must not be negative')
        if self.led_count <= 0:
            raise ValueError('Device segment led_count must be greater than zero')
        if self.start + self.led_count > self.device.led_count:
            raise ValueError('Device segment must fit within device led_count')
        return self


class DeviceSegmentFrame(BaseModel, frozen=True):
    segment: DeviceSegment
    frame: SkipValidation[NDArray[np.float32]]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ConcatLightPatchConfig(BaseModel, frozen=True):
    pass


class ConcatLightPatchState(BaseModel):
    pass


class ConcatLightPatch(Patch[ConcatLightPatchConfig, ConcatLightPatchState]):
    devices: list[animation.Device | DeviceSegment]
    patch: SkipValidation[LightPatch]

    @model_validator(mode='after')
    def validate_devices(self) -> ConcatLightPatch:
        if not self.devices:
            raise ValueError('ConcatLightPatch requires at least one device')
        return self

    def make_state(self, msg: mido.Message) -> ConcatLightPatchState:
        return ConcatLightPatchState()

    def receive(self, msg: mido.Message) -> None:
        self.patch.receive(msg)

    def render(self) -> list[DeviceSegmentFrame]:
        segments = [
            device
            if isinstance(device, DeviceSegment)
            else DeviceSegment(device=device, start=0, led_count=device.led_count)
            for device in self.devices
        ]
        virtual_device = animation.Device(
            led_count=sum(segment.led_count for segment in segments)
        )
        virtual_frame = animation.validate_frame(
            virtual_device, self.patch.render(virtual_device)
        )
        frames = []
        start = 0
        for segment in segments:
            end = start + segment.led_count
            frames.append(
                DeviceSegmentFrame(
                    segment=segment,
                    frame=animation.validate_frame(
                        animation.Device(led_count=segment.led_count),
                        np.ascontiguousarray(virtual_frame[start:end]),
                    ),
                )
            )
            start = end
        return frames


def add_light_frames(
    device: animation.Device, frames: list[NDArray[np.float32]]
) -> NDArray[np.float32]:
    if not frames:
        return animation.validate_frame(
            device, np.zeros((device.led_count, 3), dtype=np.float32)
        )
    total = np.zeros_like(animation.validate_frame(device, frames[0]))
    for frame in frames:
        total += animation.validate_frame(device, frame)
    return np.clip(total, 0.0, 1.0)

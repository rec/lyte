from __future__ import annotations

from abc import ABC, abstractmethod

import mido
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, SkipValidation, model_validator

from . import animation


class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None


class Patch[ConfigT: BaseModel, StateT: BaseModel](BaseModel, ABC):
    config: ConfigT
    state: StateT | None = None

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
        if msg.type in ('note_on', 'note_off'):
            if self.state:
                self.note_off()
                self.state = None
            if msg.velocity and msg.type == 'note_on':
                self.state = self.make_state(msg)
            return
        if self.state:
            if msg.type == 'control_change' and msg.control == 2:
                self.breath_control(msg)
            elif msg.type == 'pitchwheel':
                self.pitch_bend(msg)

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


class AdditiveLightPatchConfig(BaseModel, frozen=True):
    pass


class AdditiveLightPatchState(BaseModel):
    pass


class AdditiveLightPatch(LightPatch[AdditiveLightPatchConfig, AdditiveLightPatchState]):
    patches: list[SkipValidation[LightPatch]]

    def make_state(self, msg: mido.Message) -> AdditiveLightPatchState:
        return AdditiveLightPatchState()

    def receive(self, msg: mido.Message) -> None:
        for patch in self.patches:
            patch.receive(msg)

    def render(self, device: animation.Device) -> NDArray[np.float32]:
        if not self.patches:
            return animation.validate_frame(
                device, np.zeros((device.led_count, 3), dtype=np.float32)
            )
        return add_light_frames(
            device, [patch.render(device) for patch in self.patches]
        )


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

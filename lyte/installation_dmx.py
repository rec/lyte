"""Portable fixture profiles, installation values and Art-Net delivery."""

import math
import tomllib
from pathlib import Path

from pydantic import BaseModel
from reccy.runtime import logging
from ufor.fixture import ByteOrder, FixtureProfile

from . import artnet, dmx, installation_config, runtime_control

LOGGER = logging.get_logger(__name__)


class FixturePlayback:
    def __init__(self, config: installation_config.InstallationFile) -> None:
        self.config = config
        self.profiles = {n: read_profile(f.profile) for n, f in config.dmx.items()}
        self.instruments: dict[str, dmx.DmxInstrument] = {}
        self.values: dict[str, dict[str, float | str]] = {}
        for name, fixture in config.dmx.items():
            profile = self.profiles[name]
            if {p.name for p in profile.parameters} != {
                c.parameter for c in profile.channels
            }:
                raise ValueError(
                    f'{name}: every parameter requires a DMX channel encoding'
                )
            if set(fixture.defaults) != {p.name for p in profile.parameters}:
                raise ValueError(
                    f'{name}: defaults must supply every fixture parameter'
                )
            if profile.stop.kind != 'blackout':
                raise ValueError(
                    f'{name}: installation requires a blackout stop profile'
                )
            self.instruments[name] = dmx.DmxInstrument(
                name=name,
                universe=fixture.universe,
                start_channel=fixture.start_channel,
                channel_count=max(s for c in profile.channels for s in c.slots),
                categories=[
                    dmx.RawChannels(
                        name=c.parameter,
                        channels=c.slots
                        if c.byte_order == ByteOrder.coarse_fine
                        else list(reversed(c.slots)),
                    )
                    for c in profile.channels
                ],
            )
            self.encode(name, fixture.defaults)
            self.encode(name, fixture.defaults | fixture.blackout)
        # Validate footprint overlap and endpoint addressing before any hardware opens.
        defaults = self.render(None, runtime_control.MidiPerformance(), True)
        for frame in defaults.values():
            assert config.artnet is not None
            artnet.artdmx_packet(frame, 1, config.artnet.universe_offset)
        for definition in config.animations.values():
            for name, values in definition.fixtures.items():
                self.encode(name, config.dmx[name].defaults | values)
            for control in definition.controls:
                if control.fixture is None:
                    continue
                profile = self.profiles[control.fixture]
                parameter = next(
                    (p for p in profile.parameters if p.name == control.parameter), None
                )
                if parameter is None or parameter.choices:
                    raise ValueError(
                        'MIDI fixture controls require a declared numeric parameter'
                    )
                bounds = (
                    control.values
                    or control.output
                    or installation_config._CONTROL_RANGES[control.source]
                )
                for value in bounds:
                    self.encode(
                        control.fixture,
                        config.dmx[control.fixture].defaults
                        | {control.parameter: value},
                    )

    def encode(self, name: str, values: dict[str, float | str]) -> dmx.InstrumentOutput:
        profile = self.profiles[name]
        if set(values) != {p.name for p in profile.parameters}:
            raise ValueError(f'{name}: unknown or missing fixture parameter')
        raw: dict[str, int] = {}
        for channel in profile.channels:
            value = values[channel.parameter]
            if channel.values:
                if not isinstance(value, str) or value not in channel.values:
                    raise ValueError(
                        f'{name}.{channel.parameter}: unknown named value {value!r}'
                    )
                raw[channel.parameter] = channel.values[value]
            else:
                assert channel.minimum is not None and channel.maximum is not None
                if (
                    isinstance(value, str)
                    or not math.isfinite(value)
                    or not channel.minimum <= value <= channel.maximum
                ):
                    raise ValueError(
                        f'{name}.{channel.parameter}: value outside profile domain'
                    )
                progress = (value - channel.minimum) / (
                    channel.maximum - channel.minimum
                )
                raw[channel.parameter] = round(
                    progress * (256 ** len(channel.slots) - 1)
                )
        return dmx.InstrumentOutput(
            instrument=self.instruments[name], values=dmx.DmxValues(raw=raw)
        )

    def render(
        self,
        definition: installation_config.BoundAnimation | None,
        performance: runtime_control.MidiPerformance,
        blackout: bool,
    ) -> dict[int, dmx.DmxFrame]:
        self.values = {n: f.defaults.copy() for n, f in self.config.dmx.items()}
        if definition is not None:
            for name, values in definition.fixtures.items():
                self.values[name].update(values)
            for control in definition.controls:
                if control.fixture is not None:
                    self.values[control.fixture][control.parameter] = control.map(
                        performance
                    )
            blackout |= definition.activation == 'note' and performance.note is None
        if blackout:
            for name, fixture in self.config.dmx.items():
                self.values[name].update(fixture.blackout)
        return dmx.render_universes([self.encode(n, v) for n, v in self.values.items()])


class ArtNetStatus(BaseModel):
    state: str = 'ready'
    host: str
    universes: list[int]
    frame_count: int = 0
    failure_count: int = 0
    last_error: str | None = None


class ArtNetOutput:
    def __init__(
        self, endpoint: artnet.ArtNetEndpoint, universes: list[int], timeout: float
    ) -> None:
        self.driver = artnet.ArtNetDriver(endpoint)
        self.timeout = timeout
        self.status = ArtNetStatus(host=endpoint.host, universes=universes)

    def send(self, frames: dict[int, dmx.DmxFrame]) -> bool:
        success = True
        for universe, frame in frames.items():
            try:
                self.driver.open(timeout=self.timeout)
                self.driver.send({universe: frame})
            except (OSError, RuntimeError, ValueError) as error:
                if self.status.last_error != str(error):
                    LOGGER.error(f'Art-Net delivery failed: {error}')
                self.status.state = 'failed'
                self.status.failure_count += 1
                self.status.last_error = str(error)
                success = False
            else:
                self.status.frame_count += 1
        if success:
            self.status.state = 'sending (unconfirmed)'
            self.status.last_error = None
        return success

    def close(self) -> None:
        self.driver.close()
        if self.status.state != 'failed':
            self.status.state = 'stopped'


def read_profile(path: Path) -> FixtureProfile:
    with path.open('rb') as source:
        return FixtureProfile.model_validate(tomllib.load(source))

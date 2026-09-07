# Installation Lighting Plan

## Goal

Implementation status: the software work is complete. Fixture-profile,
network, visible-output, and blackout validation remain to be performed on the
target installation.

Run Twinkly pixel strings and DMX lighting from one Lyte installation. The
installation owns lifecycle, timing, cue selection, and shutdown. Each lighting
family keeps its useful native authoring model:

- Twinkly continues to render logical `float32` RGB frames with shape
  `(led_count, 3)` and encodes them only at its output boundary.
- DMX renders validated 512-slot universe buffers whose channel meanings come
  from instrument definitions.

This is not a proposal to turn Twinkly frames into DMX channels, or to make
DMX fixtures pretend to be pixels. The shared layer schedules independent
output tracks against the same monotonic installation clock.

## Installation Model

An installation is a named set of output targets and a run configuration. It
can contain any number of Twinkly strings and DMX instruments. A target has a
program, mutable state, output rate, and driver.

```text
Installation
  Twinkly target: PixelAnimation -> TwinklyTrack -> Twinkly HTTP and UDP
  DMX target:     DmxProgram -> DmxFrame -> DMX transport
```

The installation runner must:

1. use one monotonic clock;
2. render each target at its configured due time;
3. keep per-target state separate;
4. deliver each validated output to its target driver;
5. surface target-specific failure status without hiding failures from other
   targets; and
6. request blackout or safe output from every driver during shutdown.

The initial runner should be synchronous and single-threaded. It should find
the next due target, sleep until then, and render/send it. Transport-specific
blocking problems should be addressed at that transport boundary rather than
by introducing generic concurrency.

## DMX Fundamentals

A DMX universe is an integer identity plus exactly 512 unsigned-byte slots.
Universe numbering is an installation convention and remains explicit in
configuration; Art-Net address conversion belongs to the Art-Net driver.

A DMX instrument is an immutable definition of one contiguous range in one
universe:

```text
DmxInstrument
  name: str
  universe: int
  start_channel: int       # one-based DMX address, 1 through 512
  channel_count: int       # instrument range must end at or before 512
  categories: list[DmxChannelCategory]
```

All category channel addresses are one-based offsets within the instrument,
not absolute universe addresses. Moving an instrument therefore changes only
`start_channel`. Validation converts an offset to an absolute universe slot,
rejects a range outside the instrument, and rejects a category that overlaps
another category unless both explicitly describe the same documented control.

`DmxFrame` is a validated `numpy.uint8` array of shape `(512,)`. A program
renders a mapping from universe identity to `DmxFrame`; a transport sends it.
Programs do not know whether the frames go through Art-Net, sACN, or a USB DMX
interface.

## Typed Channel Categories

Fixture profiles use semantic category dataclasses rather than anonymous raw
channel lists. Each category owns one or more channel collections. A collection
is an ordered non-empty `list[int]` of relative instrument offsets, allowing a
profile to describe coarse/fine values or a manufacturer-specific multi-channel
control without exposing raw universe addresses to programs.

The initial category dataclasses are:

- `BrightnessChannels(channels: list[int])`: dimmer or intensity control.
- `RgbChannels(red: list[int], green: list[int], blue: list[int])`: RGB color
  components, each with one or more slots.
- `WhiteChannels(channels: list[int])`: white or amber-like additive color
  component when a fixture provides it.
- `ChaseSpeedChannels(channels: list[int])`: fixture-local chase or effect
  speed.
- `PatternSelectChannels(channels: list[int], patterns: dict[str, int])`:
  named built-in fixture patterns mapped to their documented DMX values.
- `StrobeChannels(channels: list[int])`: strobe rate or shutter strobe range.
- `PanChannels(channels: list[int])` and `TiltChannels(channels: list[int])`:
  movement axes.
- `ColorWheelChannels(channels: list[int], colors: dict[str, int])` and
  `GoboSelectChannels(channels: list[int], gobos: dict[str, int])`: named
  wheel selections.
- `RawChannels(name: str, channels: list[int])`: an intentional escape hatch
  for a documented fixture control that has no semantic category yet.

Every category is a frozen Pydantic model. The parsed configuration is a
discriminated union keyed by `kind`, for example `kind = "brightness"` or
`kind = "rgb"`. Validation must require non-empty collections, values in
`1..channel_count`, and unique addresses across categories. `RawChannels` is
permitted but must be named in the instrument definition so a profile remains
readable.

Category dataclasses describe profile capability, not animation state. A DMX
program sets semantic values such as brightness, RGB, chase speed, or named
pattern selection. The instrument encoder uses the category definition to
write the corresponding universe slots. Programs that need exact control may
write `RawChannels`, but still render through the same `DmxFrame` validation.

## Configuration Shape

Installation TOML separates output wiring from program selection. The complete
example is maintained in `examples/installation.toml`:

```toml
[artnet]
host = "192.0.2.20"

[twinkly.tree]
host = "192.0.2.10"
led_count = 250
fps = 30

[dmx.front_wash]
universe = 1
start_channel = 1
channel_count = 8
fps = 40

[[dmx.front_wash.categories]]
kind = "brightness"
channels = [1]

[[dmx.front_wash.categories]]
kind = "rgb"
red = [2]
green = [3]
blue = [4]

[[dmx.front_wash.categories]]
kind = "chase_speed"
channels = [5]

[[dmx.front_wash.categories]]
kind = "pattern_select"
channels = [6]
patterns = { static = 0, chase = 64, sound_active = 192 }

[[dmx.front_wash.categories]]
kind = "raw"
name = "reserved"
channels = [7, 8]

[programs.tree_rainbow]
kind = "pixel"
impl = "lyte.animations.bibliopixel.rainbow.Rainbow"

[programs.front_wash_chase]
kind = "dmx"
brightness = 0.5
rgb = [1.0, 0.25, 0.0]
chase_speed = 1.0
pattern = "chase"

[run.tree]
program = "tree_rainbow"

[run.front_wash]
program = "front_wash_chase"
```

`dmx.front_wash.categories` references relative offsets. In this example the
instrument owns universe 1 channels `1..8`; RGB uses absolute DMX channels
`2..4`. A second copy of the fixture can use the same category definition at a
different `start_channel` without changing program logic.

## Module Boundaries

The implementation adds protocol-specific modules without moving existing
Twinkly code:

```text
lyte/
  animation.py       existing pixel animation contract
  twinkly/           existing Twinkly protocol and realtime playback
  dmx.py             universe, frame, instrument, categories, program contract
  artnet.py          ArtDmx packet encoding and sender
  installation.py    target scheduling, lifecycle, status, shutdown
  show.py            declarative parsing and offline preflight
```

`show.py` accepts only Twinkly devices and performs no output. The installation
command is the live multi-output path. The existing MIDI daemon stays a
Twinkly wearable workflow.

## Delivery Order

1. Complete: add `dmx.py` with `DmxFrame`, universe validation, `DmxInstrument`, and the
   typed category dataclasses.
2. Complete: add parsing and validation for DMX instrument TOML. Test valid fixtures,
   range overflow, empty category collections, duplicate channels, and invalid
   pattern values.
3. Complete: add `DmxProgram` and its state contract. Implement a small semantic program
   that sets brightness, RGB, chase speed, and pattern selection for a fixture.
4. Complete: add a pure instrument encoder from semantic output to universe frames. Test
   exact byte positions and values, including multiple instruments sharing one
   universe.
5. Complete: add `artnet.py` as the first DMX transport. Test ArtDmx packet bytes, the
   configured universe conversion, sequence handling, and black-frame output.
6. Complete: add `installation.py` with fake-clock and fake-driver tests for mixed
   Twinkly and DMX due times, independent state, one target failure, and global
   shutdown.
7. Complete: add `lyte installation run` after the runner can coordinate real
   Twinkly and Art-Net drivers. Keep `lyte show` as offline preflight until
   this command is ready.
8. Field validation: replace the generic example with the physical DMX
   instrument definition and verify its category mapping, Art-Net universe,
   refresh rate, and blackout on the actual fixture.
9. Deferred: add sACN or USB DMX only when a concrete output interface requires it. They
   consume the same universe frames and must not change instrument profiles or
   DMX programs.

## Acceptance Criteria

- One installation runs a Twinkly target and a DMX target on the same clock.
- A DMX instrument validates its single universe and contiguous channel range.
- Every configured common control is represented by a typed category dataclass
  with one or more relative channel offsets.
- Semantic DMX programs encode expected values into exact universe slots.
- Invalid channel ranges, duplicate assignments, unsupported category values,
  and malformed pattern tables fail during configuration loading.
- Art-Net packets are regression-tested without network hardware.
- Target failures and shutdown results are visible per target in installation
  status.
- Physical verification confirms the chosen fixture profile, universe, output
  rate, and blackout behavior.

## Additional work beyond the prompt

None.

# Multi-Protocol Lighting Plan

Lyte should become a lighting-control toolkit that can play different lighting
systems at the same time without forcing them into one shared low-level data
model. Twinkly pixels, DMX fixtures, Open Sound Control endpoints, and Art-Net
universes can share timing, cueing, and show control while keeping protocol
details local to each device family.

The central design rule is:

- animation APIs describe what a device family can render
- output drivers know how to send rendered data to hardware
- the show runner owns clocks, concurrency, cue changes, and shutdown

This keeps the current Twinkly animation work useful while making room for DMX
and other protocols whose byte meanings depend entirely on fixture profiles.

## Goals

- Play Twinkly and DMX lighting at the same time.
- Keep the current Twinkly `Animation.render(device, state)` flow.
- Add a DMX-oriented API for fixture profiles, channels, universes, and scenes.
- Support Open Sound Control as a show-control and endpoint protocol.
- Support Art-Net as a DMX-over-IP transport.
- Leave room for other major lighting protocols without designing adapter layers
  before they are needed.
- Avoid pretending that RGB pixel frames and DMX channel buffers are the same
  model.

## Non-Goals

- Do not restore the old `next_frame()` API.
- Do not replace the Twinkly RGB animation API with a DMX abstraction.
- Do not require every protocol to support every feature.
- Do not add network discovery, GUI control, or fixture libraries in the first
  step unless a concrete implementation task requires them.

## Current Twinkly Model

The existing Twinkly API is already a good model for addressable RGB devices:

- `Animation`: immutable animation description
- `Device`: immutable hardware description
- `State`: mutable playback state
- rendered frame: `NDArray[np.uint8]` shaped `(led_count, 3)` in RGB order

That should remain the pixel-device API. It is simple, previewable, and maps
cleanly to Twinkly realtime UDP frames.

The first rename worth considering later is conceptual rather than behavioral:
`Device` could become `PixelDevice`, or stay as-is inside a `lyte.pixel` module.
Do not do that rename until there is a concrete protocol split to justify the
churn.

## DMX Model

DMX should get its own high-level model. A DMX frame is a 512-channel universe,
but the meaning of each byte depends on fixture profile and address.

Core DMX types should eventually include:

- `Universe`: immutable universe identity and channel count.
- `FixtureProfile`: immutable channel layout for a fixture model.
- `Fixture`: immutable fixture instance with profile, universe, and start
  address.
- `DmxState`: mutable playback state for DMX animations or scenes.
- `DmxProgram`: immutable object that renders fixture/channel values.
- `DmxFrame`: validated byte buffer for one universe.

A fixture profile should name channels semantically. For example, a moving head
profile might expose `pan`, `tilt`, `dimmer`, `shutter`, `color_wheel`, and
`gobo`, while a simple RGB PAR might expose `red`, `green`, `blue`, and
`dimmer`. The renderer should set semantic attributes and let the profile encode
them into channel bytes.

The API should support two authoring styles:

- low-level channel programming for exact byte control
- fixture-level programming for semantic controls

Those are both useful. They should share the same final `DmxFrame` validation
and transport path.

## Open Sound Control

Open Sound Control should be treated as both:

- a control input protocol for triggering cues, setting parameters, and syncing
  with music tools
- an output protocol for devices or software that accept OSC directly

OSC is message-oriented rather than frame-oriented. It should not be forced into
the DMX universe model. Instead, it should have an endpoint driver that sends
timestamped or immediate OSC messages produced by a program.

Possible OSC abstractions:

- `OscEndpoint`: host, port, namespace, and timing options
- `OscMessage`: address plus typed arguments
- `OscProgram`: renders zero or more OSC messages for a tick
- `OscInput`: maps incoming OSC messages to show parameters or cue triggers

OSC input should be added after the runner has a clear cue and parameter model.
Until then, output-only OSC is simpler and easier to test.

## Art-Net

Art-Net should be the first DMX transport target because it maps directly to
DMX universes over IP and is common in lighting software and hardware nodes.

Art-Net support should sit below the DMX model:

- DMX programs render `DmxFrame` values keyed by universe.
- The Art-Net driver packets those frames as ArtDmx messages.
- The runner sends frames at the configured DMX refresh rate.

Art-Net-specific concepts should stay in the driver:

- network address
- port and net/subnet/universe addressing
- sequence number
- physical port
- packet formatting

The DMX authoring API should not need to know whether output is Art-Net, sACN,
USB DMX, or a test recorder.

## Other Major Protocols

The architecture should leave clear places for these protocols:

- sACN / E1.31: another DMX-over-IP transport, often used interchangeably with
  Art-Net at the show level.
- USB DMX: local serial or USB interface transport for rendered DMX universes.
- MIDI: control input for cues, faders, notes, and clock, not a lighting frame
  transport.
- MQTT: slower automation/control integration for home or installation systems.
- WLED / DDP / E1.31 pixels: pixel output families that may share RGB frame
  rendering but require different drivers.
- Philips Hue or other smart lights: stateful device APIs with low refresh
  rates, best modeled separately from realtime pixel or DMX rendering.

Do not implement protocol-neutral abstractions for all of these upfront. The
important part is to keep driver boundaries narrow enough that each can be added
without changing existing animation APIs.

## Shared Show Runner

The shared runner is the real integration point. It should play multiple tracks
against one clock:

```text
Show
  Track: Twinkly pixels -> PixelAnimation -> Twinkly realtime driver
  Track: DMX fixtures   -> DmxProgram     -> Art-Net driver
  Track: OSC endpoint   -> OscProgram     -> OSC driver
```

Each track should have:

- a target device or endpoint
- a program or animation
- mutable state
- a frame or tick rate
- a driver

The runner should:

- maintain a monotonic show clock
- tick each track at its own configured rate
- call each program's render method with that track's device and state
- validate rendered output at the driver boundary
- send each output through its protocol driver
- stop all outputs cleanly on shutdown

This can be implemented without `async` at first. A single-threaded scheduler can
compute the next due track, sleep until it is due, render it, and send it. If a
driver later blocks too long for reliable timing, that should be addressed as a
specific transport problem.

## Proposed Package Shape

The package can grow by adding protocol-specific modules rather than expanding
the current `lyte.animation` module indefinitely:

```text
lyte/
  pixel.py          existing Animation, Device, State, validate_frame
  twinkly.py        Twinkly client, discovery, auth, realtime sender
  dmx.py            Universe, FixtureProfile, Fixture, DmxFrame, DmxProgram
  artnet.py         Art-Net packet encoding and sender
  osc.py            OSC message and endpoint support
  show.py           shared runner, tracks, clock, cue hooks
  preview.py        pixel preview, later maybe DMX/fixture inspectors
```

This is a target shape, not a required first patch. The smallest first step can
add DMX modules while leaving current Twinkly modules in place.

## API Sketch

The pixel API can stay close to the current shape:

```python
state = animation.initial_state(pixel_device)
frame = animation.render(pixel_device, state)
pixel_driver.send(frame)
```

The DMX API should expose fixture semantics and then render to channel bytes:

```python
state = program.initial_state(rig)
frames = program.render(rig, state)
artnet_driver.send(frames)
```

Where `frames` is a mapping from universe to `DmxFrame`.

The show runner should not care whether the rendered payload is a pixel frame,
DMX universe frame, or OSC message list. It should care only that each track has
a renderer and a driver with compatible payload types.

## Migration Plan

1. Rename nothing. Add a plan and keep the existing Twinkly API stable.
2. Add a small `lyte.show` model with `Track` and a single-threaded scheduler
   that can run independent render/send pairs.
3. Move Twinkly realtime playback behind a track-compatible driver without
   changing animation behavior.
4. Add `lyte.dmx` with `Universe`, `DmxFrame`, and validation for 1-512 channel
   buffers.
5. Add low-level DMX channel programs that render exact universe bytes.
6. Add `FixtureProfile` and `Fixture` for semantic fixture authoring.
7. Add `lyte.artnet` packet encoding and tests using recorded bytes.
8. Connect DMX programs to Art-Net through the shared runner.
9. Add OSC output after the runner/track shape is stable.
10. Add OSC input only after cue and parameter semantics exist.
11. Add sACN or USB DMX when there is real hardware or a concrete test target.

## Testing Strategy

Tests should stay deterministic and protocol-boundary focused:

- pixel animations compare rendered arrays
- DMX frame tests compare exact byte buffers
- fixture profile tests verify semantic values encode to expected channels
- Art-Net tests compare packet bytes for known universe frames
- OSC tests compare message address and typed argument encoding
- runner tests use fake clocks and fake drivers

Network sends should be unit-tested by patching sockets or drivers. Device demos,
live discovery, and hardware smoke tests should stay out of the normal test
suite.

## Design Warnings

The main risk is inventing a generic lighting abstraction too early. RGB pixels,
DMX fixtures, and OSC endpoints do not share the same useful low-level model.
They only need to share timing, cueing, state lifecycle, and output scheduling.

The second risk is burying fixture-specific behavior inside raw byte programs.
Low-level DMX byte control is necessary, but fixture profiles are what make DMX
usable across more than one light model.

The third risk is letting transports leak into authoring APIs. A DMX program
should render universes. Art-Net, sACN, and USB DMX should be interchangeable
ways to send those universes.

## Additional work beyond the prompt

None.

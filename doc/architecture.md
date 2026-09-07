# Lyte Architecture

## Scope

Lyte is a Python 3.13 lighting player for Twinkly pixel strings and DMX
instruments. It renders stateful RGB animations locally, encodes semantic DMX
programs into universe frames, and provides interactive, preview, diagnostic,
wearable-patch, MIDI-daemon, and mixed-installation workflows.

## Top-Level Structure

```text
lyte CLI
  |- animate, patch play, FPS tests, verify
  |    -> TwinklyTrack -> Twinkly HTTP/UDP transport -> Twinkly device
  |
  |- preview
  |    -> animation construction -> standalone HTML
  |
  |- diagnostic and Twinkly control commands
  |    -> Twinkly HTTP transport
  |
  |- installation
  |    -> shared monotonic scheduler
  |    -> pixel animation -> Twinkly realtime output
  |    -> DMX program -> universe frame -> Art-Net output
  |
  |- daemon
       -> MIDI input -> patch selector -> TwinklyTrack
       -> Reccy service, status, and local RPC
```

`lyte/cli.py` is the Tyro command table. Command configuration is represented
by frozen dataclasses, with Pydantic models used for runtime and persisted data.

## Animation Model

`lyte/animation.py` defines the core rendering contract:

- `Animation` is an immutable description of an effect.
- `Device` is an immutable description of the logical pixel device. It currently
  contains only `led_count`.
- `State` is mutable playback state. It carries the frame counter and active
  FPS; individual animations define more specific state subclasses.
- `Animation.render(device, state)` returns a C-contiguous, finite
  `numpy.float32` frame of shape `(led_count, 3)`.

The three columns are RGB channels and logical values conventionally range from
`0.0` to `1.0`. `byte_light_frame_from_float()` clips and rounds this frame to
Twinkly's `uint8` RGB payload at the output boundary. Animations must not work
in Twinkly packet bytes.

Animation implementations live in `lyte/animations/`:

- `bibliopixel/` contains the ported pattern collection.
- `christmas/` contains Hamiltonian and random-walk effects plus their support
  code.
- `colors.py` and `validators.py` hold shared animation helpers.

`SegmentAnimation` combines consecutive logical pixel regions. It owns a child
`State` for each child animation and concatenates their validated frames.

## Playback and Twinkly Output

`lyte/twinkly/track.py` owns realtime playback. A caller supplies a byte-frame
renderer and, optionally, a function that handles input before each frame.

The track:

1. authenticates and switches the device to realtime mode;
2. renders and sends one UDP realtime frame per frame interval;
3. probes the device over HTTP every two seconds, because successful UDP writes
   do not prove that the device received a frame;
4. enters recovery after a failed send or failed probe, then discovers,
   verifies, authenticates, and restores realtime mode;
5. attempts an off-mode blackout on exit, with a three-second deadline.

Realtime frame sends are one-shot. They do not use the general exponential
retry schedule, so a failed frame transfers promptly into recovery instead of
blocking the frame loop.

`lyte/twinkly/` contains the Twinkly boundary:

- `client.py`: HTTP client, authentication token lifecycle, and response
  validation.
- `authentication.py`: challenge-response calculation.
- `discovery.py`: UDP discovery packet parsing.
- `frame.py`: realtime UDP packet encoding and send.
- `session.py` and `realtime.py`: bounded authentication, mode changes,
  discovery, recovery, health probes, and device shutdown.
- the remaining modules implement the explicit diagnostic and device-control
  commands.

The `retry.py` helper is generic. It accepts an optional deadline and stop event
so setup and recovery can be cancelled without waiting through a retry delay.

## Wearable Patches and MIDI

`lyte/midi.py` defines the generic patch lifecycle. A `Patch` has immutable
configuration and optional mutable note state; a `LightPatch` renders a logical
RGB frame. Note on creates state, note off clears it, CC 2 is breath control,
and pitch wheel is forwarded while a note is active. MIDI configuration names
channels `1` through `16`; conversion to Mido's zero-based channels is isolated
at input filtering.

`lyte/patches.py` implements the wearable layer above that lifecycle:

- it loads and validates the patch-library TOML;
- `WearableSpec` describes logical regions and the mapping from them to physical
  Twinkly indices;
- layers compile to standard animation implementations;
- `RegionLightPatch`, additive `BlendLightPatch`, and
  `WeightedBlendLightPatch` compose layer frames;
- `DeclarativeLightPatch` applies note, breath, and pitch bindings before
  rendering;
- the physical map is applied by `encode_wearable_frame()` immediately before
  Twinkly byte encoding.

A wearable map is `provisional`, `guessed`, or `measured`. Playback and the
MIDI daemon reject a provisional map. A guessed map is allowed for testing but
is explicitly warned about.

## MIDI Daemon and Local Control

`lyte/daemon_runtime.py` runs the foreground daemon, and `lyte/daemon.py`
provides its service command. It starts Reccy before attempting Twinkly
connection so status and stop requests remain available during startup and
recovery.

The daemon owns one patch selector and one Twinkly track. It processes MIDI
without blocking output while a port is unavailable, clears the active note on
a confirmed disconnect, and reopens the port periodically. Program changes
advance through the configured patch list. Reccy's local RPC accepts status,
blackout, stop, named patch selection, and a white fade test command. Patch
selections and tests are queued and are applied by the frame loop; status
reports both queue and applied generations for patch selections, queued and
active light tests, and output frame-send counters.

Wearable patch libraries declare an authored LED count. When a connected string
reports a different count, Lyte warns and derives a runtime layout by scaling
logical and physical map boundaries to the actual count. The configured map is
unchanged; recovery still requires the established runtime count.

Daemon status records lifecycle state, Twinkly host and MAC, the most recent
output contact and frame send, MIDI state, recovery count, output failures,
render failures, and the most recent failure. Connection changes, failed health
probes, and UDP send errors are recorded through Reccy logging. Render failures
produce a black frame and identical repeated failures are counted without
publishing an unbounded stream of events.

The daemon configuration loader is `lyte/daemon_config.py`. Its TOML references
a patch library, an ordered patch list, MIDI input settings, Twinkly connection
settings, and FPS.

## Other Workflows

`lyte/animate/` builds and plays an individual animation or a randomized show
with crossfades. It shares `TwinklyTrack` with patch playback.

`lyte/preview/` builds the same animation descriptions but renders them to a
standalone HTML file. It has no hardware connection.

`lyte/fps_test.py` contains visual diagnostic workflows for frame rate, fades,
temporal dithering experiments, black-floor testing, and feature verification.

`lyte/show.py` parses and validates TOML show files, merges compatible files,
constructs named animation graphs, and allocates independent device/state pairs
for run targets. `lyte show` is an offline preflight command only: it does not
open a device, render a frame, or play a show.

## DMX and Installation Playback

`lyte/dmx.py` defines the DMX authoring boundary. A `DmxInstrument` owns one
contiguous channel range in one universe. Its frozen category models describe
brightness, RGB, white, chase speed, pattern selection, strobe, movement,
color wheels, gobos, and named raw controls using relative one-based channel
offsets. Instrument validation rejects out-of-range and duplicate assignments.

A `DmxProgram` renders semantic `DmxValues`. The instrument encoder converts
those values into a C-contiguous 512-slot `uint8` `DmxFrame`. Multiple
non-overlapping instruments can contribute to one universe frame.

`lyte/artnet.py` converts universe frames into ArtDmx packets and owns UDP
delivery, sequence numbers, universe conversion, and blackout frames. DMX
programs and instrument definitions do not depend on Art-Net and can later use
another universe transport without changing their authoring model.

`lyte/installation.py` loads mixed installation TOML and builds independent
pixel and DMX targets. Its single-threaded scheduler uses one monotonic clock,
runs each target at its own frame rate, preserves independent state, records
per-target output failures, and attempts blackout and close on every opened
driver. Twinkly targets reuse `TwinklyTrack` connection health and recovery;
DMX targets sharing an Art-Net endpoint retain one combined universe state.

The installation command is the live mixed-output workflow. `lyte show`
remains an offline Twinkly graph preflight command and continues to reject
non-Twinkly devices.

## Testing Boundaries

`tests/` is organized by subsystem. Unit tests use fake clocks, MIDI ports,
HTTP responses, UDP senders, and Reccy connections. They cover parsing,
validation, frame conversion, patch composition, recovery decisions, and CLI
dispatch.

Physical device behavior remains outside the automated suite. Power cycling a
Twinkly, Wi-Fi loss, MIDI unplug/replug, the wearable physical map, and Art-Net
fixture addressing and blackout require explicit manual validation on the
actual playback system.

## Extension Boundaries

New pixel animations should implement `Animation` and keep changing data in a
`State` subclass. New wearable effects should normally be expressed as patch
layers and bindings before adding new patch-composition primitives.

Additional universe transports should consume `DmxFrame` without changing DMX
programs or instrument profiles. Additional output families should define
their own device and frame model and join the installation scheduler only when
their render and driver boundaries are concrete.

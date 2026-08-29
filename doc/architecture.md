# Lyte Architecture

## Scope

Lyte is a Python 3.13 lighting player for one Twinkly pixel string. It renders
stateful RGB animations locally, encodes them for the Twinkly realtime protocol,
and provides interactive, preview, diagnostic, wearable-patch, and MIDI-daemon
workflows.

The implemented runtime is Twinkly-specific. DMX, Art-Net, OSC, and other
lighting protocols are not part of the current architecture.

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
reports both queue and applied generations for patch selections.

Daemon status records lifecycle state, Twinkly host and MAC, the most recent
output contact, MIDI state, recovery count, render failures, and the most recent
failure. Render failures produce a black frame and identical repeated failures
are counted without publishing an unbounded stream of events.

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

## Testing Boundaries

`tests/` is organized by subsystem. Unit tests use fake clocks, MIDI ports,
HTTP responses, UDP senders, and Reccy connections. They cover parsing,
validation, frame conversion, patch composition, recovery decisions, and CLI
dispatch.

Physical device behavior remains outside the automated suite. Power cycling a
Twinkly, Wi-Fi loss, MIDI unplug/replug, and the wearable physical map require
explicit manual validation on the actual playback system.

## Extension Boundaries

New pixel animations should implement `Animation` and keep changing data in a
`State` subclass. New wearable effects should normally be expressed as patch
layers and bindings before adding new patch-composition primitives.

A future non-Twinkly output should not be forced into the current RGB pixel
frame or Twinkly track abstractions. It should define its own device and frame
model, then join a higher-level runner only when that runner has a concrete
multi-device scheduling contract.

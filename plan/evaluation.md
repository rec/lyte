# Project Evaluation

This is an evaluation of the current repository, not an implementation plan.
It distinguishes implemented behavior from design documents and identifies
constraints that should be made explicit before further feature work.

## Current Shape

Lyte is operationally a Twinkly Generation 2 RGB controller with a substantial
collection of RGB animations, device diagnostics, HTML preview, and frame-rate
experiments. The recently added wearable work can parse a TOML catalogue,
compile the catalogue into logical `LightPatch` graphs, and show a provisional
region locator.

The repository also contains several forward-looking documents for float light
channels, patches, show files, DMX, Art-Net, OSC, and external control signals.
Most of those concepts are not yet runtime features. This is reasonable, but
names and documents can currently imply more integration than exists.

## Inconsistent Models

### Frames and devices

The current runtime is specifically RGB:

- `Device` contains only `led_count`.
- `Animation.render()` and `LightPatch.render()` validate exactly `(led_count,
  3)` `float32` frames.
- Twinkly encoding is exactly three `uint8` channels per LED.

`plan/floating-point.md` correctly describes a general light-channel frame, but
that abstraction has not been implemented. `doc/api-plan.md` and parts of
`plan/dmx.md` still describe `uint8` RGB animation output and an older Python
compatibility model. An author cannot tell from the documents which contract is
current without reading code.

This matters before RGBW, warm/cool white, RGBAL, single-channel, or two-channel
lights are introduced. Generalizing only the final encoder will not be enough:
RGB animations need an explicit color conversion policy, while a fixture or
non-RGB strand needs a channel layout and a semantic definition of gain, white,
and color mixing.

### Declarative patches and executable patches

`patches/wearable-breath.toml` has both executable-looking tables and prose
control fields such as `breath_speed = "CC 2 maps ..."`. The catalogue compiles
layer names, but the prose controls do not affect rendering. The five registered
layer kinds are also much less specific than their names imply. For example,
`hamiltonian_stream` is registered as a rainbow layer and `binary_counter` as a
chase layer.

The result is a difficult mental model: a patch name may suggest a specific
visual or MIDI behavior that the compiled graph does not implement. The list
command reports control labels that are only documentation. This is more
misleading than a smaller catalogue of executable patches would be.

### Patch composition

`RegionLightPatch`, `BlendLightPatch`, `WeightedBlendLightPatch`,
`UnionLightPatch`, and `ConcatLightPatch` overlap without a single composition
vocabulary. The first three render one logical RGB device, `UnionLightPatch`
returns a dictionary of frames, and `ConcatLightPatch` returns physical segment
frames. No shared output or scheduling layer consumes all of those results.

In particular:

- `build_light_patch()` creates a logical frame but does not apply the wearable
  physical map.
- `WeightedBlendLightPatch` is not selected by the TOML compiler, so the
  documented breath-mix entries remain additive blends.
- `ConcatLightPatch` models contiguous slices of devices, while the wearable
  map needs non-contiguous ranges. The two models cannot compose directly.
- the selected logical regions are applied to every layer in a patch, so the
  current file cannot express a chest-only layer plus limb-only layer without
  creating additional patch definitions.

These are useful primitives, but their roles need to settle before more
combiners are added.

### Show files

`ShowFile` parses, merges, validates references, and resolves Python paths, but
`lyte show` does not instantiate an animation graph or start playback. The
show-file plan describes a full route from named sources to devices and mixers;
the runtime currently stops after resolution. Import paths also mean a show file
is executable Python configuration. That may be acceptable for a personal tool,
but it should be an explicit trust boundary rather than an incidental parser
feature.

## Control and MIDI Limits

The current MIDI model is a local callback API, not a complete MIDI input
system. There is no port-opening loop, input lifecycle, timestamp handling,
queue, filtering implementation, or patch playback command that binds a Mido
input to a Twinkly output.

`Patch.receive()` is deliberately monophonic. Any `note_off`, or any `note_on`
including a different note, clears the sole state. It does not check the note or
MIDI channel that created that state. This matches a simple wind-controller
workflow, but it will surprise users of keyboards, layered controls, sustain,
or multiple controllers.

Only CC 2 and pitch wheel are routed, and their behavior is defined by optional
methods on patch classes. There is no timestamped show-level control value,
control mapping, smoothing, takeover policy, range policy, or representation of
missing/stale input. MIDI input cannot yet control several devices through a
single named parameter as proposed in `plan/dmx.md`.

No concurrent input exists today, so there is no current thread race. The first
background Mido listener or REST/Art-Net receiver will create one: it could
mutate a patch's Pydantic state while the render loop reads it. Mutable lists in
region state and blend weights make partially observed updates possible. A
single runner-owned event queue and tick-boundary state update would avoid
making locking an accidental requirement of every patch.

## Offline and Failure Behavior

The present output loops assume a device can be reached promptly. This is a
reasonable first controller behavior but not a show-control behavior.

- Each HTTP request can block for the configured timeout, normally five
  seconds. Retry delays and backoff then block the same thread further.
- `send_realtime_frame()` retries UDP send errors and then exits the command.
  UDP send success only reports local socket acceptance, not that Twinkly
  received, decoded, or displayed the frame.
- A lost connection, expired token, device reboot, Wi-Fi roam, or cable outage
  is terminal for animation and locator playback. There is no reconnection,
  reauthentication, resume policy, or distinction between a short outage and a
  deliberately removed device.
- `run_animate()` and the locator call `prepare_device()` before entering their
  `try`/`finally` cleanup regions. A failure after the device enters realtime
  mode can bypass their normal off operation.
- Cleanup itself has finite retries. When the device is offline, failure is
  logged and the process ends, but the physical output state is unknown. This
  is unavoidable while disconnected, and a future runner must report it as
  unknown rather than claim blackout succeeded.
- Discovery has two incompatible defaults. `discover_host()` can retry forever
  with `None`, diagnostic commands use that behavior, but `lyte animate`
  defaults to a five-second discovery timeout.

A future multi-device runner also needs explicit per-device failure policy.
One unavailable Twinkly should not necessarily stop Art-Net output, and a DMX
transport may need to keep sending its last or black frame continuously even
when an unrelated device is recovering.

## Timing and Concurrency Limits

Animation playback uses one synchronous loop that renders, encodes, sends, and
sleeps. It has no deadline accounting outside the FPS test commands. A slow
render, UDP retry, HTTP operation, garbage collection pause, or logging burst
causes the next frame to be late. It does not skip, coalesce, or report normal
animation frame overruns.

Random animation crossfades render and send two animations sequentially on the
same clock. There is no shared scheduler for independent device frame rates.
The current model cannot play a Twinkly at one rate and a DMX universe at another
rate without one loop being blocked by the other.

Art-Net and sACN need predictable repeated universe output, sequence handling,
and per-universe refresh. DMX fixture control also commonly expects persistent
levels rather than a frame only when an animation happens to render. The current
Twinkly frame loop is not a reusable basis for that behavior without separating
track timing, rendering, output, and recovery.

## Multi-Protocol Boundaries

`plan/dmx.md` makes the correct high-level distinction between RGB pixels and
DMX fixture channels, but no runtime boundary exists yet. Current protocol and
animation code are coupled in several places:

- `lyte.animation` assumes RGB and an LED count.
- `lyte.twinkly.realtime` owns discovery, authentication, realtime mode,
  sending, and shutdown as one flow.
- CLI commands repeat Twinkly connection configuration and device handling.
- the patch module imports Twinkly realtime code, so a nominally declarative
  patch library cannot be loaded as a general non-Twinkly component.

DMX needs fixture profiles, channel values, universes, addresses, and output
transports. Art-Net is only one possible sender for those universes. OSC output
is message-oriented, and slow smart lights need a different rate and state
model again. A common runner can share lifecycle and clocking, but forcing all
of these into `Animation.render(Device, State) -> RGB frame` would lose the
semantics that make DMX useful.

The conceptual limit to preserve is therefore narrow: share show time, track
lifecycle, control values, scheduling, observability, and shutdown policy. Do
not share a low-level frame or device class merely for uniformity.

## Usability Risks

The CLI exposes a large set of Twinkly endpoint commands, diagnostics, test
commands, animation commands, preview, show parsing, and partial patch support.
It is useful for exploration but does not clearly distinguish stable playback
from diagnostics and experiments. `README.md` still describes the project as a
small dependency-free Twinkly proof of concept, despite `numpy`, `pydantic`,
`mido`, and `tyro` dependencies and a much larger scope.

Configuration is split between animation arguments, patch TOML, show TOML, and
many duplicated CLI connection fields. There is no single user-visible concept
for a device identity, device profile, physical layout, output mapping, and
connection policy. That will become harder to explain with more than one light
or protocol.

The wearable physical map is explicitly provisional, which is good, but it is
also relied on by the locator and future patches. The `physical_map_status` is
informational only. Nothing prevents a performance command from using an
unmeasured map once such playback exists.

## Tests and Verification Gaps

The test suite has broad unit coverage for parsing, frame encoding, endpoint
request construction, CLI dispatch, and many legacy animations. It does not yet
provide confidence in the integrated behavior that future work depends on.

Important gaps include:

- no physical-device regression or recorded protocol fixture covers discovery,
  authentication, realtime preparation, streaming, interruption, and cleanup
  as one lifecycle;
- no test simulates a Twinkly failure after entering realtime mode, a token
  expiry during UDP playback, a multi-second outage, or failed shutdown;
- no test measures animation-loop frame deadlines under a slow send or retry;
- no test confirms that a compiled wearable patch is mapped from logical indexes
  to the physical frame before output;
- no test exercises live Mido port input, ordering of note/control events, or
  future concurrent render and input access;
- no test verifies that the thirty-two catalogue entries have the advertised
  distinct control behavior, because that behavior does not yet exist;
- no fixture profile, universe buffer, Art-Net packet, sACN packet, OSC message,
  or multi-track scheduler test exists.

There is also test concentration. `tests/test_lyte.py` contains more than two
hundred tests across all subsystems. It mixes unit tests, CLI dispatch tests,
HTTP fakes, animation behavior, and timing utilities. This makes failures hard
to locate and encourages repeated mock setup. Several CLI tests primarily prove
that `isinstance` dispatch reaches an already-tested command function; they
have lower value than tests of command parsing, validation, and observable
behavior. Splitting tests by subsystem would make missing integration coverage
more visible without requiring more total tests.

## Questions to Resolve Before Broad Expansion

1. Is Lyte first a reliable personal Twinkly player, or is the next priority a
   generic show runner? Both are valid, but recovery and abstractions differ.

Answer: The first step is to concentrate on making a personal Twinkly played, but
I have many DMX lights that I want to use within the year.

2. What output state should each device hold during an outage: last frame,
   blackout, protocol default, or a device-specific policy?

Answer: blackout

3. What is the exact contract for a control event: timestamp, source identity,
   ordering, lifetime, and mapping to active notes or tracks?

CC 2 from the selected MIDI input and channel applies immediately to the currently
active note’s patch; it persists until the next CC 2 or that note ends; events are
processed in input arrival order.


4. Which existing patch names are commitments to a visual behavior, and which
   are placeholders for later design work?

All are experimental placeholders for later work

5. At what boundary should RGB be converted into a device's actual light
   channels and color calibration model?

As later as possible. My plan is to port BiblioPixel's ideas, which include

6. Which components are trusted to execute Python paths from a show file?

Everything is trusted. This is all intended to run on a small, disposable machine.


## Additional work beyond the prompt

None.

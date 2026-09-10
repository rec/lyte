# Lyte Architecture

## Scope

Lyte is the rendering and output host for Ufor light scores. Ufor owns portable
score discovery, references, presets, layouts, component contracts, animation
settings, composition, timing, and scalar modulation. Lyte owns NumPy effect
implementations, mutable playback state, HTML preview encoding, Twinkly
HTTP/UDP output, wearable MIDI patches, DMX encoding, Art-Net, and service
lifecycle.

Ufor has no dependency on Lyte or NumPy. Lyte pins a tested Ufor revision.

## Command Boundaries

```text
Ufor library config -> score selection -> Composition -> PreparedAnimation
                                            |              |
                                            |              +-> HTML preview
                                            |              +-> Twinkly bytes
                                            |
installation TOML -> DMX program ------------------------------> Art-Net

wearable patch TOML -> MIDI patch renderer --------------------> Twinkly
```

`lyte show`, `lyte preview`, `lyte animate`, and installation pixel
programs all use `show.prepare_animation()` or its already-read-library
equivalent. The old Lyte show graph, `impl` strings, and recursive Python
construction no longer exist.

## Library Preparation

`lyte/show.py` calls `ufor.library_files.read_library()`. With no explicit
path, Ufor reads `~/.config/ufor/library.toml`; an explicit path replaces the
default. Reading creates no files. Ufor discovers independent entries, records
diagnostics, binds relative paths and selectors, verifies optional hashes,
normalizes presets, detects cycles, and constructs a `Composition`.

A `LightProgramSpec` selects:

- one score by literal Ufor selector;
- one named light output;
- public scalar parameter overrides;
- an optional physical `Wiring` order.

All library diagnostics are logged, including fields and cycle paths. An
unrelated rejected entry does not prevent a ready score from playing. Missing,
ambiguous, blocked, non-animation, unsupported-effect, incompatible-component,
or invalid-wiring selections fail during preparation, before output opens.

Python score files use the explicit `rendering.PythonAnimationScore` contract.
Ufor retains the declared class but does not infer playback methods. Lyte
requires that exact subclass, creates one state per prepared part, and invokes
its typed state and frame methods. Score roots are never added to `sys.path`.

## Rendering

`lyte/rendering.py` carries the selected Ufor `LightType`. Every logical
frame is a finite, C-contiguous `numpy.float32` array with shape:

```text
(len(layout.lights), len(components))
```

Generic Ufor operations support any positive component count:

- `Fill` repeats one component vector.
- `Mix` sums weighted frames and clips at that mix boundary.
- `Place` maps child rows to ordered, named output lights.
- `Reverse` reverses lights only.
- `Gain` scales without clipping.
- `Crossfade` blends without clipping.
- `Cues` use exact rational timing, cue-local ticks, and black gaps.
- `ComponentMap` applies an explicit output-row by input-column matrix.

Nested mixes retain their own clipping. Placement, gain, crossfade, and
component mapping preserve values outside `[0, 1]`. Final byte conversion
clips and rounds once.

Each prepared part path owns one mutable state. Repeated selection of the same
part is cached for a logical tick and advances once. Separate parts referencing
the same score have independent states. Stateful effects advance on integer
logical ticks at the score's rational rate. Output delivery may repeat a frame
or omit delivery of an intermediate frame, but it does not alter the simulation
step sequence.

Public parameters are validated by `Composition.parameter_contract()`.
Presets and caller overrides are resolved by Ufor. Live updates rebuild the
prepared parameter graph while retaining part state. Built-in effect parameter
updates are reported as construction-only because some effect fields determine
state shape or random initialization; generic scalar operations such as
`Gain` can update without resetting children.

## Built-In RGB Effects

`lyte/animate/build.py` is the explicit registry from all 41
`ufor.effects` tags to installed Lyte renderers. Score data cannot load an
arbitrary import path. The Ufor description remains the runtime source of
settings; Lyte's renderer classes and dedicated state classes supply behavior.

These extracted algorithms require exactly `red`, `green`, `blue` drive
components in that order. Other component contracts use generic operations and
must author an explicit `ComponentMap` where conversion is intended. Lyte
does not infer RGBW, dimmer, warm/cool, or linear-sRGB conversion.

`lyte/animations/` groups implementation code into `patterns`, `fields`,
`events`, and `simulations`. The older composition classes remain an
internal part of the wearable patch engine; Ufor operations are the only
composition format accepted by show, preview, animate, and installation pixel
programs.

## Layout and Wiring

Ufor `Layout` list order is logical frame order. Coordinates may be irregular
and one-, two-, or three-dimensional. Strip effects continue to use logical
order unless an algorithm explicitly reads coordinates. HTML previews use the
authored coordinates and never apply physical wiring.

`Wiring.indexes(layout)` is computed during preparation and applied once,
immediately before physical byte output. It changes light order only, not
component order. A score layout count must match the installation target count;
Lyte does not stretch authored score geometry to hide a mismatch. Wearable
patch scaling is a separate, explicit host policy for the guessed garment map.

## Twinkly Output

`lyte/twinkly/track.py` owns realtime playback. It authenticates, enters
realtime mode, sends one-shot UDP frames, probes HTTP health every two seconds,
and enters bounded recovery after failed sends or probes. Recovery verifies the
established LED count and MAC address. Shutdown attempts off-mode blackout
within three seconds.

Successful UDP writes are not health evidence. Connection, disconnection,
probe, send, recovery, MAC mismatch, LED-count mismatch, and blackout failures
are recorded through Reccy logging.

## Wearable Patches and Daemon

`lyte/patches.py` loads the wearable patch catalogue and its logical regions.
`lyte/midi.py` owns note, breath, and pitch lifecycle. The foreground daemon
in `lyte/daemon_runtime.py` combines MIDI input, patch selection,
`TwinklyTrack`, Reccy service status, and local RPC.

The current wearable map is guessed and authored for 250 lights. Its explicit
host policy warns and scales region and physical-map boundaries when the
attached string count differs. This does not alter Ufor score layouts.

The daemon RPC supports status, blackout, stop, named patch selection, and a
configurable white fade test. Status includes queued and applied selections,
queued and active tests, connection identity, output contact, frame sends,
MIDI state, recovery counters, failures, and the latest error.

## DMX and Mixed Installations

`lyte/dmx.py` defines a DMX instrument as one universe and one contiguous
channel range. Typed categories describe brightness, RGB, white, chase speed,
pattern selection, strobe, movement, color wheels, gobos, and named raw
channels. The encoder produces C-contiguous 512-byte universe frames.

`lyte/artnet.py` owns ArtDmx packet encoding, sequence numbers, UDP delivery,
universe conversion, and blackout. Installation DMX programs are currently
static semantic values.

`lyte/installation.py` runs Twinkly and DMX targets on one monotonic
scheduler. Pixel programs are Ufor selectors. Each target records failures
independently, and shutdown attempts blackout and close for every opened
driver. Target FPS controls delivery; the Ufor score rate controls logical
animation ticks.

## Testing Boundary

Automated tests cover score preparation, diagnostics, all effect registrations,
generic one- through five-component composition, exact cue behavior, state
ownership, presets, live gain, wiring, authored preview geometry, deterministic
renderer fixtures, Twinkly recovery, MIDI, DMX bytes, Art-Net packets, mixed
scheduling, and shutdown.

They do not prove visible output, Wi-Fi recovery on a specific controller,
wearable routing, fixture addressing, or physical blackout. Those remain
explicit checks on the show hardware.

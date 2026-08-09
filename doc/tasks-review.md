# Review of Completed Tasks

## Scope

This review covers the task work from `062b3f9 Add Twinkly playback connection
state` through `2c0a357 fixup! Add show playback state`. It reviews the
resulting code and tests, not only the individual commit messages. No physical
Twinkly or MIDI device was exercised for this review.

The work falls into five groups:

- Twinkly connection state, cleanup, recovery, and frame-deadline reporting.
- Mido input selection and monophonic patch playback.
- The declarative 200-dot wearable patch library and physical map.
- Current RGB float-frame contracts and documentation.
- Trusted local-Python Show File loading and in-memory run targets.

The changes are useful foundations, but several completed checklist items
should be narrowed or followed by a corrective commit before they are treated
as finished end-user features.

## Findings Requiring Follow-up

### 1. `lyte show` does not play a show

`run_show()` loads files, builds `ShowGraph`, creates `ShowPlayback`, and
returns success. It does not call `render_show_target()`, open a Twinkly
connection, send a frame, manage frame timing, or perform blackout cleanup.

This makes the completed Show Files task misleading in two places:

- `tasks.md` calls it graph construction and playback.
- `plan/file-format.md` says its example streams an animation to a Twinkly.

An end user can reasonably expect `lyte show example.toml` to operate the
light, but it currently only validates and constructs objects in memory.

Correction: either rename the command and checklist item to an explicit
preflight/validation operation, or implement a Twinkly track that consumes
`ShowPlayback`. The latter belongs with the deferred shared playback work,
not inside the Show File parser.

### 2. Breath and pitch speed do not reset when a note ends

`DeclarativeLightPatch.apply_bindings()` calls `set_layer_speed()`, which
replaces the `RegionLightPatch.config` with a new configuration containing the
mapped speed. `Patch.end_note()` clears the active state and CC 2 value, but it
does not restore the original layer configuration.

Consequently, after a note ends, the next note starts at the previous note's
breath or pitch-controlled speed until a new control event arrives. This
contradicts the agreed CC 2 lifetime: the control value persists until the next
CC 2 or that note ends.

Correction: keep each layer's configured base animation immutable. Store
per-note speed in `DeclarativePatchState`, and have rendering derive the
animation parameters from that state, or rebuild the layer state from the
original `LayerSpec` on every note-on. Add a regression test covering note-on,
CC 2 or pitch bend, note-off, then a fresh note-on without another control
message.

### 3. Patch playback does not use the new Twinkly recovery policy

Normal `lyte animate` treats a failed frame send as a recovery event and calls
`recover_streaming_device()`. In contrast, `stream_patch_frames()` only logs
`[failed] Could not stream patch frame` and continues sending subsequent
frames. It neither requests blackout nor re-discovers, re-authenticates, and
restores realtime mode.

The command also has no deadline reporting. A long retry or network timeout
simply delays MIDI polling and rendering. This is a substantial practical
limitation because `lyte patch play` is the command intended for live control.

Correction: extract the proven Twinkly output lifecycle into the small,
synchronous track runner already listed under Shared Playback. Make both
animation playback and patch playback use it. The runner should own recovery,
blackout attempts, deadline accounting, and the current output host.

### 4. The current Show File schema silently ignores important fields

`DeviceSpec.params` and `RunTargetSpec.params` retain arbitrary TOML values,
but `create_show_playback()` uses only `devices.<name>.led_count` and ignores
such fields as `host`, `brightness`, and `channel_map`. The parser accepts
those values without warning.

This is especially confusing because the plan's examples use `host` and
run-target `brightness`, and its minimal example omits `led_count`, which the
current `lyte show` command now requires.

Correction: until a Twinkly show track exists, accept only the fields used for
in-memory construction, or report that other fields are unsupported. Once a
track exists, replace opaque parameter dictionaries with a Twinkly device
configuration model and a deliberately defined run-target transform model.
Update `plan/file-format.md` at the same time.

## Important Design and Usability Issues

### Show Files are a construction graph, not yet a show runner

`ShowGraph` correctly shares an immutable `Animation` description while
`ShowTarget` gives each output separate mutable state. That is the right
ownership direction. However, it is only useful when a runner retains the
`ShowPlayback` object and advances each target over time.

`render_show_target()` is currently unused by the CLI, and
`resolve_show_file()` remains an older parallel resolution path that is also
unused by the CLI. Keeping both paths makes it unclear which object represents
the supported runtime interface.

The next implementation should select one pipeline:

```
ShowFile -> ShowGraph -> ShowPlayback -> TwinklyTrack -> output lifecycle
```

The graph and playback objects should remain protocol-neutral only up to the
point where a track is created. Do not make them pretend to be DMX device
abstractions before DMX has fixture and universe semantics.

### Layer names promise more than layer kinds provide

The wearable TOML has names such as `hamiltonian_stream`, `binary_counter`, and
`five_searchlights`, but `LayerSpec.kind` supports only `solid`,
`random_walk`, `twinkle`, `chase`, and `rainbow`. In practice several evocative
names select a generic implementation. The library is marked experimental,
which helps, but the names still imply behavior that an author cannot infer
from the schema.

Correction: either make the layer name explicitly descriptive of its current
implementation, or expand `LayerSpec` into typed implementation-specific
models. The latter should wait until there is a concrete desired behavior for
each layer. Avoid adding aliases merely to preserve the current names.

### Binding target validation is structural, not semantic

A binding can target `<layer>.speed` for every declared layer even when that
layer's current implementation has no useful speed parameter. For example, a
solid fill accepts the schema but cannot visibly respond to speed. The code
also maps all speed controls into a small set of animation parameters, where
`speed` may mean random-walk velocity, `Twinkle` timing, or integer pixel step.

Correction: validate control targets against the concrete layer kind, and
document the unit and perceptual direction of each mapping. This should be
part of a small per-layer control contract, not a generic string convention.

### The provisional physical map is safe from performance use, but not clear

The map is correctly blocked by `lyte patch play` until its status is
`measured`, while `lyte patch locator` remains available. This is a good safety
boundary. The remaining practical problem is that changing the TOML value to
`measured` is the only gate; there is no recorded evidence of what was measured
or which physical layout it describes.

Correction: when the map is verified, add a short human-maintained note near
the map with the device identity, layout, date, and locator observation. Do
not add a fake automated proof for a physical wiring fact.

### MIDI assumptions need to remain visible

The MIDI implementation intentionally supports one selected input and one
selected channel. Within that filtered stream, it is monophonic: a new note-on
replaces the active note, and only an off for that same note ends it. This is
reasonable for the stated wind-controller workflow.

The `Patch` object itself stores only a note number, not input or channel
identity. This is correct only because the input is filtered before
`Patch.receive()`. Any future route that feeds multiple channels, ports, or
threads directly to a patch must add source identity and queue events at a
render-tick boundary. It must not reuse this class as though it were generally
polyphonic.

## Reliability Review

The `PlaybackConnection` states and structured frame-send outcomes are an
improvement over terminating below the command boundary. Cleanup after
realtime setup is also now protected by `finally`, and recovery retries until a
Twinkly is reachable again.

There are still operational caveats:

- A requested blackout during an outage is a policy and a logged state, not a
  physical guarantee. A disconnected device cannot receive the off request.
- UDP send success confirms local socket acceptance, not displayed pixels.
- Recovery is synchronous and blocks rendering, input polling, and the current
  command until it succeeds. This is acceptable for the current one-device
  player, but it is not suitable as the eventual multi-track failure model.
- Frame pacing uses a relative `sleep(1 / fps - elapsed)` after each frame. It
  does not schedule against an absolute clock or skip overdue frames. The
  reported `missed_deadlines` is useful observability, but should not be read
  as an exact count of frames a fixed-rate scheduler would have emitted.
- The current recovery and cleanup tests are mocked unit tests. They verify
  control flow, not the behavior of a device that roams Wi-Fi, reboots, or
  keeps its old displayed frame after an interruption.

## Documentation Drift

The new `doc/api-plan.md` and README accurately describe the implemented
float32 RGB animation contract and Twinkly-first scope. `plan/file-format.md`
now needs the most attention: it predates the implementation and describes a
full output path, flexible device fields, and combiners that do not yet exist.

The API plan's runner snippet should also use `source.initial_state(device)`,
not `animation.initial_state(device)`, to match the actual method owner.

Documentation should keep the distinction below explicit:

- implemented: RGB float animation rendering, one-device Twinkly animation
  playback with recovery, and experimental MIDI wearable patches;
- implemented but offline only: Show File parsing, graph construction, and
  per-target state allocation;
- planned: show output tracks, multi-device scheduling, DMX, Art-Net, OSC,
  non-RGB light channels, and declarative patch playback from Show Files.

## Test Review

The added tests are focused and cover the main local contracts: transport
outcomes, recovery state, MIDI ordering/filtering, binding effects, physical
mapping, and Show File references and state independence. This is a useful
improvement over the earlier evaluation.

The tests do not yet establish the following end-user behavior:

- a patch player recovering from a token or transport failure;
- reset of per-note derived controls, especially speed;
- a Show File producing a frame or communicating with a device;
- rejection or warning for Show File options that are parsed but ignored;
- all thirty-two TOML patches producing distinct expected behavior;
- an end-to-end physical map verification or a recorded Twinkly lifecycle.

The first four should be ordinary unit tests added with their corrective code.
The final two require a deliberate physical verification procedure rather than
more mocks.

## Recommended Follow-up Order

1. Fix the per-note control reset bug and add its regression test.
2. Correct the Show File wording, examples, and completed-task description, or
   implement a clearly scoped single-Twinkly Show File runner.
3. Move recovery, blackout, and deadline handling into a reusable synchronous
   Twinkly track, then make patch playback use it.
4. Tighten the wearable binding schema around concrete layer capabilities.
5. Record the physical-map verification when the wearable is measured.
6. Begin the deferred shared playback and DMX work only after the Twinkly track
   has one lifecycle contract used by both animation and patch commands.

## Commit Notes

The commits are generally small and grouped by task. Two fixup commits remain
visible:

- `a5a8d59 fixup! Report Twinkly animation frame deadlines`
- `2c0a357 fixup! Add show playback state`

They are harmless, but should be autosquashed only when the user decides to
rewrite local history. Do not change history merely to make the log prettier.

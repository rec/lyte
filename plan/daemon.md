# MIDI Patch Daemon Plan

## Implementation Status

- [x] Program changes reach optional patch hooks.
- [x] The daemon TOML model validates ordered patch lists and requires a
  guessed or measured wearable map.
- [x] The synchronous foreground daemon reopens unavailable MIDI input and
  uses `TwinklyTrack` for output, recovery, and blackout cleanup.
- [x] `LyteMidiDaemon(Reccy)` owns foreground playback, service lifecycle,
  local control, and persisted status.
- [ ] Install the service and complete the physical MIDI, Twinkly, and locator
  verification procedure on the playback machine.

## Purpose

Run Lyte as a per-user background service on the playback machine. It starts at
login or boot, opens the configured wind-instrument MIDI input, drives one
Twinkly output through the existing `TwinklyTrack`, and selects patches from an
ordered TOML list.

This is a MIDI-input daemon. It exposes Reccy's local control endpoint for
status, blackout, stop, and configured patch selection, but creates no HTTP,
REST, OSC, or MIDI-network interface.

## Service Definition

The repository now defines `lyte.daemon_runtime.LYTE_SERVICE` with Reccy's
`ServiceSpec`:

- name: `lyte`
- launchd label: `com.swirly.lyte`
- daemon environment marker: `LYTE_DAEMON=1`

Reccy provides the per-user service definition and lifecycle mechanics:

- macOS: a `launchd` LaunchAgent with `RunAtLoad` and `KeepAlive`.
- Linux: a `systemd --user` unit with `Restart=always` and a five-second restart
  delay.
- Windows: Reccy can render a scheduled task, but Windows support is not part
  of this first daemon implementation.

`LyteMidiDaemon(Reccy)` uses `ServiceSpec` for service definitions and Reccy's
derived local paths for its control, event, and status files. Installation
invokes the installed `lyte daemon run` command using the configured daemon TOML
path and writes normal stdout/stderr logs through the platform service
definition.

## Daemon Configuration

Add a dedicated daemon TOML file. It is separate from the reusable wearable
patch library because it defines machine-local playback choices.

```toml
[daemon]
patch_library = "patches/wearable-breath.toml"
patches = ["prism_limbs", "breath_walker", "breath_mix_walk_twinkle"]
fps = 60.0

[midi]
channel = 1
device_name = "Wind Controller"

[twinkly]
timeout = 5.0
discovery_timeout = null
attempts = 10
retry_delay = 0.5
retry_backoff = 2.0
```

Rules:

- `patches` is non-empty, ordered, and contains unique patch names from the
  selected `patch_library`.
- The first name is current when the daemon starts.
- The wearable physical map must be `guessed` or `measured`; daemon startup
  rejects `provisional` maps and warns when it streams a guessed map.
- `midi` uses the existing `MidiIn` input-name and channel filtering model.
  Configuration names channels `1` through `16`; Mido's zero-based channel
  values are converted only at the input boundary.
- `twinkly` reuses existing connection and retry fields. There is still one
  Twinkly output in this version.
- The configuration is read at startup only. No live reload is needed in the
  first version.

## Program-Change Behavior

Program changes are consumed only after `MidiIn` has selected the configured
input and channel. They are not interpreted as program numbers. Each
`program_change` advances to the next configured patch and wraps from the last
entry to the first.

The daemon maintains a small MIDI performance snapshot:

- active note number and velocity, if any;
- latest CC 2 breath value for that active note;
- latest pitch-wheel value for that active note.

On a program change:

1. Construct a fresh instance of the next patch.
2. Replace the current patch at the next frame boundary.
3. If a note is active, replay its note-on, followed by the retained breath and
   pitch values, to the new patch in that order.
4. Render the replacement patch on that same output frame.

This makes a program change while blowing immediately select the next look.
A program change while idle simply changes the selected patch; its frame
remains black until the next note. The old patch is discarded, so it cannot
retain animation, control, or note state.

`Patch.receive()` needs an optional `program_change(mido.Message)` hook. The
generic `Patch` implementation should call it for `program_change` regardless
of whether a note is active. The daemon, rather than an individual wearable
patch, owns patch-list advancement.

## Runtime Lifecycle

1. Load and validate daemon TOML and its patch library before opening devices.
2. Open the selected MIDI port. If it is unavailable at service startup or later
   disconnects, log the condition and retry opening it with bounded sleep until
   it is available. Do not crash-loop the service manager for an unplugged
   controller.
3. Resolve the Twinkly device and LED count, build a `TwinklyTrack`, and call
   `prepare()`.
4. Construct the first configured patch, start `LyteMidiDaemon`, and enter one
   synchronous frame loop.
5. Before each frame, drain available filtered MIDI messages in arrival order,
   update the performance snapshot, and handle any program changes.
6. Render the selected patch, map its logical wearable frame, and provide its
   byte frame to `TwinklyTrack.stream_frames()`.
7. On a Twinkly send failure, retain the selected patch and performance
   snapshot while `TwinklyTrack` performs its current blackout and recovery
   lifecycle. Resume rendering the same patch after recovery.
8. On `SIGTERM`, `KeyboardInterrupt`, or any render exception, close the MIDI
   port and call `TwinklyTrack.close()` so Lyte attempts normal blackout
   cleanup.

The loop remains synchronous. MIDI messages are applied immediately before the
render that consumes them, so no separate listener can mutate a patch while it
renders.

## Proposed Modules

- `lyte/daemon.py`: define the Tyro daemon command dataclass and delegate
  service lifecycle actions to `LyteMidiDaemon`.
- `lyte/daemon_config.py`: immutable Pydantic models for daemon TOML and
  validation of patch list, MIDI input, and Twinkly settings.
- `lyte/daemon_runtime.py`: `LyteMidiDaemon(Reccy)`, its persisted status and
  local control handling, plus the synchronous MIDI frame callback.
- `lyte/midi.py`: route `program_change` to the optional patch hook.
- `lyte/cli.py`: add a `daemon` command with `run`, `install`, `uninstall`,
  `start`, `stop`, `restart`, and `status` actions.

Do not add a web server, REST interface, or generic control-event queue. Use
only Reccy's local control endpoint.

## Tests

Add focused unit tests for:

- daemon TOML validation: empty lists, duplicate names, unknown patch names,
  and provisional physical maps;
- first patch selection at startup and wraparound after the final patch;
- program changes filtered by configured MIDI channel;
- program changes while idle and while a note is active;
- replay order of note, breath, and pitch into a newly selected patch;
- frame-boundary replacement, proving the old patch is not rendered after the
  program-change frame;
- MIDI port unavailable at startup and disconnect/reopen behavior;
- Twinkly recovery retaining patch selection and active control snapshot;
- cleanup after startup, MIDI, render, and Twinkly failures;
- Reccy-generated macOS and Linux service definitions containing the daemon
  command, service label, logs, startup behavior, restart behavior, and
  Reccy-derived local control paths.

Physical verification after implementation:

1. Install the service on the intended playback machine.
2. Reboot or log in and confirm the first patch is selected before MIDI input.
3. Send program changes at rest and while sustaining breath, confirming
   immediate wraparound and no stale patch output.
4. Disconnect and reconnect the MIDI controller and Twinkly separately.
5. Stop the service and confirm the lights are blacked out.

## Implementation Order

1. Add and test `program_change` routing in `Patch`.
2. Implement and test daemon TOML parsing and patch-list validation.
3. Implement the in-process synchronous daemon runtime with fake MIDI and
   Twinkly track tests.
4. Add the Tyro `lyte daemon run` foreground command and verify cleanup.
5. Move daemon lifecycle, local control, and status publication into
   `LyteMidiDaemon(Reccy)`.
6. Perform the physical service and MIDI verification procedure above.

## Additional Work Beyond the Prompt

None.

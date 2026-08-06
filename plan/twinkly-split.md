# Twinkly Split Plan

Move Twinkly-specific code under a `lyte/twinkly/` package while preserving the
current command behavior. Start with file moves and import rewrites only. After
that package boundary exists, split the pieces that currently mix generic Lyte
concepts with Twinkly transport, discovery, authentication, and device state.

## Goals

- Put Twinkly protocol, device, discovery, and realtime transport code under
  `lyte/twinkly/`.
- Keep generic animation and preview code independent of Twinkly hardware.
- Keep `lyte` commands working while the package is split.
- Make later DMX or other protocol work easier by leaving generic runner and
  frame concepts outside the Twinkly package.

## Non-Goals

- Do not redesign the CLI in this pass.
- Do not change Twinkly HTTP or UDP behavior.
- Do not add compatibility aliases for old internal module paths unless tests or
  current public imports require a temporary transition.
- Do not move generic animation classes, preview rendering, logging, retry, or
  MIDI control into the Twinkly package.

## Target Layout

```text
lyte/
  animation.py              generic Animation, Device, State, frame validation
  animations/               generic animation implementations
  cli.py                    top-level tyro command dispatch
  logging.py                generic console reporting
  preview.py                generic HTML preview rendering
  retry.py                  generic retry helper
  twinkly/
    __init__.py             public Twinkly surface
    authentication.py       challenge response and MAC helpers
    client.py               Twinkly HTTP client and response/token models
    discovery.py            Twinkly UDP discovery
    diagnostic.py           Twinkly diagnostic and endpoint reports
    frame.py                Twinkly realtime UDP packet encoding/sending
    realtime.py             shared Twinkly realtime setup/send/shutdown helpers
    realtime_diagnostic.py  Twinkly realtime diagnostic command implementation
    session.py              Twinkly auth/session helpers and request labels
    control.py              brightness, mode, layout, movie, playlist commands
```

`lyte/network/` should disappear or become protocol-neutral only if a future
non-Twinkly network abstraction needs it. The current files in that directory are
Twinkly-specific despite the generic directory name.

## Phase 1: Pure Moves

Move files without changing behavior:

1. Move `lyte/network/authentication.py` to `lyte/twinkly/authentication.py`.
2. Move `lyte/network/client.py` to `lyte/twinkly/client.py`.
3. Move `lyte/network/discovery.py` to `lyte/twinkly/discovery.py`.
4. Move `lyte/network/frame.py` to `lyte/twinkly/frame.py`.
5. Move `lyte/network/session.py` to `lyte/twinkly/session.py`.
6. Move `lyte/twinkly.py` to `lyte/twinkly/control.py`.
7. Move `lyte/diagnostic.py` to `lyte/twinkly/diagnostic.py`.
8. Move `lyte/realtime_diagnostic.py` to `lyte/twinkly/realtime_diagnostic.py`.
9. Update imports in `lyte/__init__.py`, `lyte/cli.py`, `lyte/runtime.py`,
   `lyte/fps_test.py`, `lyte/animate/device.py`, tests, and any docs.
10. Add `lyte/twinkly/__init__.py` for the Twinkly public surface used by the CLI
    and tests.

This phase should not rename classes or functions except where imports require
package qualification. It should be one commit if tests pass cleanly.

## Phase 2: Extract Shared Twinkly Realtime Helpers

`lyte/fps_test.py` and `lyte/animate/device.py` both contain Twinkly setup,
frame sending, device shutdown, LED count, and discovery behavior. Move the
shared implementation into `lyte/twinkly/realtime.py`:

- `send_realtime_frame`
- `read_led_count`
- `prepare_device`
- `turn_off_device`
- `turn_off_streaming_device`
- `discover_host`
- retry-forever discovery behavior used by realtime tests

Then make `lyte/animate/device.py` either disappear or become a tiny animation
runner adapter that imports Twinkly realtime helpers. If it only delegates, remove
it and import Twinkly realtime helpers directly from `lyte/animate/playback.py`.

## Phase 3: Split Mixed Diagnostic Types

`TwinklyDeviceInfo` and `TwinklyEndpointReport` are Twinkly-specific. Keep them
inside `lyte/twinkly/diagnostic.py` or split them into `lyte/twinkly/models.py` if
multiple Twinkly modules need them.

`DiagnosticConfig` is mixed: its fields are generic command runtime settings,
but today it exists only for Twinkly diagnostics and Twinkly control commands.
For now, keep it in `lyte/twinkly/diagnostic.py`. Later, if DMX or other devices
reuse the same shape, extract a neutral `DeviceCommandConfig` or `NetworkConfig`
under `lyte/cli.py` or a generic command module.

## Phase 4: Split Twinkly Control Commands

`lyte/twinkly/control.py` will still be large after the move. Split it by device
feature once the package import path is stable:

- `output.py`: brightness and saturation models plus get/set helpers.
- `mode.py`: LED mode, static color, effects.
- `layout.py`: layout coordinate/model plus layout and LED config commands.
- `timer.py`: timer model and command.
- `media.py`: movies and playlists.
- `networking.py`: WiFi status and scan commands.
- `inputs.py`: MQTT, mic, and music read-only commands.

Keep `lyte/twinkly/control.py` as the CLI-facing coordinator only if it removes
real duplication. Otherwise, import feature commands directly in `lyte/cli.py`.

## Phase 5: Decide What Is Truly Generic

After Twinkly-specific code is contained, review classes and helpers for names
that sound generic but are still Twinkly-specific:

- `LyteClient` should probably become `TwinklyClient` because it speaks Twinkly
  HTTP endpoints and Twinkly auth.
- `LyteResponse` can become `TwinklyResponse` unless another protocol reuses the
  exact same JSON response model.
- `UnsupportedEndpointError` can either stay generic as a protocol error or move
  into `lyte/twinkly/errors.py` if only Twinkly uses it.
- `runtime.py` should probably disappear after its functions move into
  `lyte/twinkly/realtime.py` or `lyte/twinkly/session.py`.

Do these renames after the physical move, not at the same time. They are semantic
changes and should be separate commits.

## Verification

For each implementation commit:

1. Run `uv run pytest`.
2. Run `uv run ruff check --fix --select B,E,F,I lyte scripts tests`.
3. Run `uv run ruff format`.
4. Run `uv run ty check lyte scripts tests`.
5. Run pyupgrade with the project Python version.
6. Confirm no stale imports reference old Twinkly paths.

Do not run real-device commands as part of this split.

## Additional Work Beyond the Prompt

None.

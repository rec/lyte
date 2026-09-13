# Lyte Handover

## Normal Operation

Start with a read-only device check:

```sh
lyte diagnostic
```

Validate and play a registered Ufor light score:

```sh
lyte show examples:/composition.toml --library-config examples/library.toml
lyte animate examples:/composition.toml --library-config examples/library.toml
```

List registered animation scores or generate a hardware-free preview:

```sh
lyte preview --library-config examples/library.toml
lyte preview examples:/composition.toml preview.html --library-config examples/library.toml
```

Render MP4 demonstrations without hardware:

```sh
lyte render examples:/composition.toml --library-config examples/library.toml \
  --output movies
```

Omit selectors to render every animation score in the selected library.
`ffmpeg` must be on `PATH`. Use `--diameter`, `--padding`, `--shape`,
`--layout COLUMNS ROWS`, and `--background-color` to control the grid image.

Use `lyte patch list` to inspect the wearable patch catalogue. For an
interactive wearable session, use `lyte patch play NAME`. Use `Ctrl-C` to stop
an interactive command; it requests a bounded blackout before returning.

Direct Twinkly commands assume one discoverable device on the local network.
Leave their host options unset unless that assumption stops being true.

The default Ufor library configuration is
`~/.config/ufor/library.toml`. An explicit `--library-config` replaces it.
Selectors are literal and may use a library name, score name, tags, or address.
Lyte logs rejected and blocked library entries but can still play an unrelated
ready score.

## Daemon Operation

The default daemon configuration is
`patches/wearable-daemon.toml`. Run it in the foreground while setting up:

```sh
lyte daemon run
```

Install and manage the per-user service when the foreground setup is stable:

```sh
lyte daemon install
lyte daemon status
lyte daemon restart
lyte daemon stop
```

`lyte daemon install` records an absolute path to the selected configuration.
After changing the daemon TOML, run `lyte daemon restart`.

The daemon's Reccy endpoint accepts status, blackout, stop, named patch
selection, and a white fade test. Status distinguishes queued and applied patch
selections, queued and active tests, connection state, recent output contact,
frame sends, recovery, and failures. The test command's level is a percentage
and its duration is the complete fade-up and fade-down time.

Use service status as the first check after a failed performance setup. For a
stale or disconnected MIDI device, reconnect the device and wait for the daemon
to reopen it; restarting is not normally required. For a Twinkly outage, restore
power or Wi-Fi and allow the daemon to reconnect before intervening further.

## Configuration Ownership

`patches/wearable-daemon.toml` is machine-local show configuration:

- `patch_library` is resolved relative to this file.
- `patches` is the ordered performance list.
- `fps` sets the daemon frame rate.
- `transition_duration` in `[daemon]` sets patch crossfade time in seconds
  (default 0.25); zero selects immediate switching.
- `[midi]` selects the MIDI channel and optionally a device name or ordered list
  of acceptable device names.
- MIDI channel values use the musician-facing range `1` through `16`.
- `[twinkly]` holds connection and retry settings.

`patches/wearable-breath.toml` is the reusable wearable catalogue and its
current physical mapping. It currently declares `physical_map_status =
"guessed"`. Do not change that to `"measured"` until the physical string has
been checked on the garment.

The wearable count is derived from its region map unless a planning count is
declared. Lyte warns and scales the runtime layout when the attached string
reports a different count. Verify the result with the locator before performance
use.

Run the locator before a performance with a changed garment or string routing:

```sh
lyte patch locator
```

Record the observed mapping and update the TOML deliberately. Do not alter the
factory string to make the logical layout fit the file.

## Twinkly Installation Operation

`examples/installation.toml` documents two semantic Twinkly string names. A
`[twinkly]` entry matches discovered `gestalt` text, with no address, MAC, or
LED count in the document. For example, `{ product_name = "Dots" }` assigns the
Dots string; `{}` receives the only remaining discovered string.

Each `[animations.NAME]` entry selects a Ufor score and binds its named RGB
drive outputs to strings. `left + right` makes the strings one long logical
strip. `left * right` mirrors one rendered frame, independently scaled to each
detected count. Every string must appear exactly once in each animation.

The file's `library_config` is resolved relative to the installation file. Keep
installation TOML outside registered score roots so Ufor does not discover it
as a score.

Run a configured installation in the foreground:

```sh
lyte installation run installation.toml
```

Use `--duration SECONDS` for a bounded setup test. Normal completion and
`Ctrl-C` attempt Twinkly blackout before closing output sockets. The Reccy
service accepts `select_animation` with a configured name. It applies the
selection on the next frame boundary without reconnecting healthy strings.
`status` reports the selected and queued animation and each string's connection
state, detected count, frame count, and failures.

Automated tests verify selector matching, unambiguous assignment, output
expression validation, concatenated partitioning, mirrored scaling, and queued
selection. They do not verify visible output, Wi-Fi recovery, or physical
blackout.

## Safety and Recovery Expectations

The output attempts to turn off within three seconds when a normal command or
daemon session exits. A powered-off or unreachable device cannot confirm that
blackout, so remove power or use the Twinkly app if an immediate physical
blackout is required during a network outage.

Do not assume a successful command-line send proves that the physical lights are
visibly responding. Check the device after a Wi-Fi, power, or controller fault.

Before relying on the wearable in performance, perform these on the target
machine and record the result:

1. Power-cycle the Twinkly during an active output, then confirm that output
   returns without restarting Lyte.
2. Unplug and reconnect the MIDI interface during an active note, then confirm
   that the lights go dark and that a later note is accepted.
3. Stop the daemon while the Twinkly is unreachable and confirm that it returns
   promptly.
4. Run `lyte patch locator` on the assembled garment and verify every named
   region.
5. Run a bounded installation test, verify each string's visible response, and
   confirm that both strings black out on exit.

## Development Maintenance

Use `uv` for the project environment and checks:

```sh
uv run pytest
uv run ruff check --fix --select B,E,F,I lyte tests
uv run ruff format lyte tests
uv run ty check lyte
```

The two Hamiltonian checks are intentionally optional and remain skipped unless
their opt-in environment setting is supplied.

Treat the patch TOML files as executable configuration: validate them through
`lyte patch list` or the test suite after editing. `lyte show` resolves one
Ufor selector and validates the complete renderer graph; it does not operate
lights.

`examples/library.toml` registers `examples/scores/`.
`examples/scores/composition.toml` demonstrates named placement, a reversed
child, and timed cues over an explicit 250-light layout. Use the preview and
animate commands from Normal Operation to exercise exactly the same prepared
graph. Score files contain Ufor descriptions and references, never Lyte Python
implementation paths.

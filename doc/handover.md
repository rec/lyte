# Lyte Handover

## Normal Operation

Start with a read-only device check:

```sh
lyte diagnostic
```

Play an ordinary animation:

```sh
lyte animate hamiltonian --speed 80
```

Generate a hardware-free preview when choosing an effect:

```sh
lyte preview
lyte preview rainbow preview.html
```

Use `lyte patch list` to inspect the wearable patch catalogue. For an
interactive wearable session, use `lyte patch play NAME`. Use `Ctrl-C` to stop
an interactive command; it requests a bounded blackout before returning.

Direct Twinkly commands assume one discoverable device on the local network.
Leave their host options unset unless that assumption stops being true. Mixed
installation targets always require explicit host addresses in their TOML.

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

The wearable LED count is the authored layout count. Lyte warns and scales the
runtime layout when the attached string reports a different count. Verify the
result with the locator before performance use.

Run the locator before a performance with a changed garment or string routing:

```sh
lyte patch locator
```

Record the observed mapping and update the TOML deliberately. Do not alter the
factory string to make the logical layout fit the file.

## Mixed Installation Operation

`examples/installation.toml` documents one Twinkly target and one generic
eight-channel DMX instrument. Its TEST-NET addresses deliberately do not name
real installation hardware. Copy it to an installation-specific file, replace
the addresses, and replace every DMX category and pattern value with the
fixture manual's actual profile.

Run a configured installation in the foreground:

```sh
lyte installation run installation.toml
```

Use `--duration SECONDS` for a bounded setup test. Normal completion and
`Ctrl-C` attempt Twinkly and DMX blackout before closing output sockets. A
target failure is logged and counted without stopping other targets; the
command returns failure after bounded playback if any target failed.

DMX universe numbers are one-based in the installation file. Category channel
numbers are one-based offsets within the instrument's contiguous channel
range. Art-Net subtracts one from the configured universe by default when it
constructs the Art-Net port address.

Automated tests verify DMX profile validation, exact universe bytes, ArtDmx
packet bytes, mixed scheduling, independent failures, and shutdown calls. They
do not verify a fixture manual, network route, node configuration, visible
output, or physical blackout.

The current installation runner supports Art-Net output only. DMX programs are
static values in the installation file; dynamic DMX effects, DMX input, sACN,
and USB DMX are not implemented.

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
5. Run a bounded mixed installation test, verify the DMX fixture's address and
   mode against its manual, and confirm visible Art-Net output and blackout.

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
`lyte patch list` or the test suite after editing. `lyte show` validates a show
file only; it is not a command for operating lights.

Animation import paths now use `lyte.animations.patterns`, `fields`, `events`,
`simulations`, and `compositions`. Update locally authored show and installation
files that reference the former `bibliopixel`, `christmas`, or `one_d` paths.
For example, `lyte.animations.fields.rainbow.Rainbow` names the rainbow field.

`examples/composition.toml` demonstrates segments, a mirrored child, and a timed
crossfade. Use `lyte preview composition preview.html --composition-file
examples/composition.toml --width 250 --height 1` to render that graph without
hardware. `lyte animate composition --composition-file examples/composition.toml
--duration 10` plays it on a 250-LED string. Compositions use seconds for timing
and nonnegative gain/weights; existing generator colors and motion parameters
retain their prior units. Wearable patch colors are converted from normalized
RGB to the generator's byte color arguments when constructing each layer.

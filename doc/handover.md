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

The working assumption is one Twinkly on the local network. Leave host options
unset unless that assumption stops being true.

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

Use service status as the first check after a failed performance setup. For a
stale or disconnected MIDI device, reconnect the device and wait for the daemon
to reopen it; restarting is not normally required. For a Twinkly outage, restore
power or Wi-Fi and allow the daemon to reconnect before intervening further.

## Configuration Ownership

`patches/wearable-daemon.toml` is machine-local show configuration:

- `patch_library` is resolved relative to this file.
- `patches` is the ordered performance list.
- `fps` sets the daemon frame rate.
- `[midi]` selects the MIDI channel and optionally a device name or ordered list
  of acceptable device names.
- MIDI channel values use the musician-facing range `1` through `16`.
- `[twinkly]` holds connection and retry settings.

`patches/wearable-breath.toml` is the reusable wearable catalogue and its
current physical mapping. It currently declares `physical_map_status =
"guessed"`. Do not change that to `"measured"` until the physical string has
been checked on the garment.

Run the locator before a performance with a changed garment or string routing:

```sh
lyte patch locator
```

Record the observed mapping and update the TOML deliberately. Do not alter the
factory string to make the logical layout fit the file.

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

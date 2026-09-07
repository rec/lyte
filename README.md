# lyte

Lyte is a personal Python 3.13 lighting player for one Twinkly string. It
preserves a library of stateful pixel animations and provides a reliable
realtime playback path with discovery, authentication, recovery, and blackout
cleanup.

Lyte uses `numpy`, `pydantic`, `tyro`, and `mido`. Its animation contract is a
logical `float32` RGB frame; Twinkly byte encoding happens only when sending a
realtime frame.

## Commands

Inspect the connected Twinkly device:

```sh
lyte diagnostic
```

Run an animation:

```sh
lyte animate hamiltonian --speed 80
```

Inspect available animations without connecting to lights:

```sh
lyte preview
```

## Experimental Wearable Patches

`lyte patch list` lists the experimental 250-dot wearable patch library.
`lyte patch locator` may be used while its physical map is provisional.
The supplied map is a guessed two-branch layout, so `lyte patch play NAME` and
the daemon may be used for testing with a warning. Record it as `measured` only
after checking it on the assembled garment.

The current project supports Twinkly directly and DMX through Art-Net. These
remain separate output models and can run together from one installation file.

## Mixed Twinkly and DMX Installations

`lyte installation run` loads one TOML file containing Twinkly targets, DMX
instruments, typed DMX channel categories, pixel and DMX programs, and a run
map. Start from the non-runnable TEST-NET example:

```sh
cp examples/installation.toml installation.toml
lyte installation run installation.toml
```

Replace both example addresses and the generic fixture profile before running
the command. DMX output uses Art-Net. Universe numbers in configuration are
one-based by default and are converted to zero-based Art-Net port addresses by
the output driver. `Ctrl-C` requests blackout from every opened output before
returning.

DMX instrument channel numbers inside category definitions are one-based
offsets relative to the instrument's `start_channel`. Common controls use typed
categories such as `brightness`, `rgb`, `chase_speed`, `pattern_select`,
`strobe`, `pan`, `tilt`, `color_wheel`, and `gobo_select`. Use a named `raw`
category only for a documented fixture control that does not fit those
categories.

## MIDI Daemon

`patches/wearable-daemon.toml` defines the ordered wearable patch list for the
MIDI daemon. The daemon starts with its first patch and advances, wrapping at
the end, for every program-change message on the selected MIDI channel. A
program change while a note is active replays that note, its breath control,
and pitch bend into the new patch.

Run it in the foreground with:

```sh
lyte daemon run
```

Install its per-user `launchd` or `systemd --user` service with:

```sh
lyte daemon install
```

The daemon exposes Reccy's local control endpoint for status, blackout, stop,
patch selection, and a white fade test command. It accepts a guessed wearable
physical map for testing and warns before playback. Record the map as
`measured` after locator verification on the assembled garment. The `test`
command accepts `level` percent and `duration` seconds parameters.

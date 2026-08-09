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

`lyte patch list` lists the experimental 200-dot wearable patch library.
`lyte patch locator` may be used while its physical map is provisional.
Performance playback with `lyte patch play NAME` is intentionally blocked until
the TOML library records a measured physical map.

The current project is Twinkly-first. DMX, Art-Net, OSC, and other lighting
protocols remain planned work rather than supported runtime features.

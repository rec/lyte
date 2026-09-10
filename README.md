# lyte

Lyte is a Python 3.13 lighting player for Twinkly pixel strings and DMX
instruments. It provides stateful RGB animations, reliable Twinkly realtime
playback, MIDI-controlled wearable patches, and mixed Twinkly and Art-Net
installation playback.

Pixel animations render C-contiguous `numpy.float32` RGB frames. Conversion to
Twinkly's byte format happens at the output boundary. DMX instruments use typed
channel categories and render independent 512-slot universe frames.

## Twinkly Commands

Inspect the discovered device without changing it, play an animation, or list
animations that can be rendered to HTML:

```sh
lyte diagnostic
lyte animate hamiltonian --speed 80
lyte preview
```

Generate a hardware-free preview by naming an animation and output file:

```sh
lyte preview rainbow preview.html
```

Direct Twinkly playback discovers a single device when no host is supplied. It
authenticates the device, enters realtime mode, probes the HTTP connection while
streaming UDP frames, recovers after connection failures, and requests blackout
when playback ends.

## Animation Families and Compositions

Animations are organized into patterns, fields, events, simulations, and
compositions. List a family with `lyte preview --family fields`.

Compositions combine other animations using segments, weighted mixes,
crossfades, reversal, intensity envelopes, and timed sequences. The same graph
can be previewed or played:

```sh
lyte preview composition preview.html --composition-file examples/composition.toml --width 250 --height 1
lyte animate composition --composition-file examples/composition.toml --duration 10
```

`--composition-source` selects a named graph node (default `main`). The example
uses 250 logical LEDs. Graph files contain trusted Python implementation paths;
their `sources` lists reference other named nodes. Each occurrence owns its
playback state. See `doc/architecture.md` for composition semantics.

## Wearable Patches

The supplied wearable catalogue is authored for 250 LEDs split into five
logical regions. Its physical map is guessed, not measured:

```sh
lyte patch list
lyte patch locator
lyte patch play PATCH_NAME
```

Lyte warns when using the guessed map. If the connected string has a different
LED count, it warns again and scales the logical regions and physical map to the
actual count. Mark the map as `measured` only after checking every region on the
assembled garment.

`patches/wearable-daemon.toml` configures the MIDI input, ordered patch list,
Twinkly connection, and frame rate. Run the daemon in the foreground or install
its per-user service:

```sh
lyte daemon run
lyte daemon install
lyte daemon status
```

Program-change messages select the next patch. Note, CC 2 breath, and pitch-bend
messages control the active patch. The Reccy endpoint supports status, blackout,
stop, named patch selection, and a white fade test; the test level percentage
and total duration are configurable.

Patch changes during an active note crossfade for 0.25 seconds. Set
`transition_duration` in `[daemon]` to change this, or to zero for immediate
switching. Note-off cancels an active transition.

## Mixed Installations

`lyte installation run` loads Twinkly targets, DMX instruments, programs, and a
run map from one TOML file. Start with the example:

```sh
cp examples/installation.toml installation.toml
lyte installation run installation.toml --duration 10
```

The example uses non-routable TEST-NET addresses and a generic fixture profile.
Replace both addresses and define the DMX channels from the fixture manual
before running it.

DMX output currently uses Art-Net. Universe numbers and instrument
`start_channel` values are one-based. Category channel numbers are one-based
offsets within an instrument. Available categories are `brightness`, `rgb`,
`white`, `chase_speed`, `pattern_select`, `strobe`, `pan`, `tilt`,
`color_wheel`, `gobo_select`, and named `raw` channels.

Installation DMX programs are static semantic values. Pixel programs construct
an `Animation` from a trusted local Python import path. A pixel program may list
other pixel program names in `sources` to construct a composition; its `params`
configure placements, weights, envelopes, or cues. The scheduler runs each
target at its configured frame rate, records failures independently, and
requests blackout from every opened output at shutdown.

`lyte show` is a separate offline validator for Twinkly-only show graphs. It
does not connect to hardware or run an installation.

## Documentation

- `doc/architecture.md` describes the code and runtime boundaries.
- `doc/handover.md` contains operation, configuration, recovery, and physical
  validation procedures.

# lyte

Lyte is a Python 3.13 lighting player for Twinkly pixel strings and DMX
instruments. Ufor score libraries own light layouts, animation settings,
composition, and scalar controls. Lyte provides NumPy effect rendering,
reliable Twinkly realtime playback, MIDI-controlled wearable patches, and mixed
Twinkly and Art-Net installation playback.

Pixel animations render C-contiguous `numpy.float32` RGB frames. Conversion to
Twinkly's byte format happens at the output boundary. DMX instruments use typed
channel categories and render independent 512-slot universe frames.

## Twinkly Commands

Inspect the discovered device without changing it, prepare and play a Ufor
score, or list scores that can be rendered to HTML:

```sh
lyte diagnostic
lyte animate examples:/composition.toml --library-config examples/library.toml
lyte preview --library-config examples/library.toml
```

Override exported scalar controls as name/value pairs, for example
`--parameters brightness 0.5`.

Generate a hardware-free preview from the same score:

```sh
lyte preview examples:/composition.toml preview.html --library-config examples/library.toml
```

Direct Twinkly playback discovers a single device when no host is supplied. It
authenticates the device, enters realtime mode, probes the HTTP connection while
streaming UDP frames, recovers after connection failures, and requests blackout
when playback ends.

## Ufor Scores and Compositions

Register score roots in a Ufor library configuration, then select a score by
literal library, name, tag, or address. The default configuration is
`~/.config/ufor/library.toml`; `--library-config` replaces that default.
Reading a library never creates files. List one effect family with:

```sh
lyte preview --library-config examples/library.toml --family fields
```

Ufor compositions provide named placement, weighted mixes, crossfades,
reversal, gain, component mapping, and timed cues. The score declares its
logical update rate, light components, and one-, two-, or three-dimensional
layout. Preview uses those authored coordinates. Wiring is a final physical
permutation and is never applied to previews or intermediate parts.

The same 250-light graph can be validated, previewed, or played:

```sh
lyte show examples:/composition.toml --library-config examples/library.toml
lyte preview examples:/composition.toml preview.html --library-config examples/library.toml
lyte animate examples:/composition.toml --library-config examples/library.toml --duration 10
```

The example library is rooted at `examples/scores/`. Its composition places
two 125-light ripple parts into named halves, reverses one half, and cues the
result against a 250-light aurora. Ufor resolves references and presets before
Lyte prepares one state per part path. No score data contains a Python import
path.

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

Installation DMX programs are static semantic values. Each pixel program names
a Ufor selector, light output, public parameter overrides, and optional wiring.
The installation's `library_config` is resolved relative to its TOML file.
Lyte validates score resolution, renderer support, component meaning, layout
size, and wiring before opening output. The scheduler runs each target at its
configured delivery rate while preserving the score's logical simulation rate,
records failures independently, and requests blackout from every opened output
at shutdown.

`lyte show` performs the same Ufor selection and renderer preflight without
connecting to hardware or running an installation.

## Documentation

- `doc/architecture.md` describes the code and runtime boundaries.
- `doc/handover.md` contains operation, configuration, recovery, and physical
  validation procedures.

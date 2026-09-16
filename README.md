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
lyte preview examples:/composition.toml --output preview.html --library-config examples/library.toml
```

Render browser- and desktop-playable MP4 files from selected scores, or omit
the selectors to render every animation score in the library:

```sh
lyte render examples:/composition.toml examples:/aurora.toml \
  --library-config examples/library.toml --output movies
lyte render --library-config examples/library.toml --output movies
```

`lyte render` lays out LEDs in a grid. `--diameter`, `--padding`, `--shape`,
`--layout COLUMNS ROWS`, and `--background-color` control the movie image.
It requires `ffmpeg` on `PATH` and writes one H.264 MP4 per score.

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
lyte validate examples:/composition.toml --library-config examples/library.toml
lyte preview examples:/composition.toml --output preview.html --library-config examples/library.toml
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

The same 36-patch catalogue is available through Ufor selectors and the
installation runner. `patches/wearable-library.toml` registers the presets, and
`patches/wearable-installation.toml` configures the single wearable string and
shared MIDI controls:

```sh
lyte validate wearable:/prism_limbs.toml \
  --library-config patches/wearable-library.toml
lyte installation run patches/wearable-installation.toml
```

The Ufor adapter preserves the legacy algorithms and guessed physical map. The
wearable hardware is not currently available, so this path has automated
rendering coverage but still requires a physical mapping and MIDI check before
performance use.

## Twinkly Installations

`lyte installation` discovers named Twinkly strings and starts selectable
bound Ufor animations. It can run in the foreground or own the normal `lyte`
per-user service:

```sh
cp examples/installation.toml installation.toml
lyte installation run installation.toml --duration 10
lyte installation install installation.toml
lyte installation status installation.toml
```

Each `[twinkly]` entry is a case-insensitive `gestalt` selector, such as
`{ product_name = "Dots" }`; the empty selector is useful for the one remaining
device. No address, MAC, or LED count is configured. `[animations.NAME]` maps
score output names to string expressions: `left + right` treats two strings as
one long strip, and `left * right` mirrors one rendered frame to both strings.
The Reccy RPC command `select_animation` queues a declared animation for the
next frame boundary. `status` reports the active and queued animation plus
per-string connection, count, frame, and failure status. The same endpoint
supports `test`, `blackout`, and `stop`.

An optional `[midi]` table enables MIDI input and reconnection. An animation may
set `activation = "note"` and map `gate`, `note`, `velocity`, CC 2 `breath`, or
`pitch_bend` into public Ufor score parameters:

```toml
[[animations.reactive.controls]]
source = "breath"
parameter = "brightness"
output = [0.0, 1.0]
```

`velocity` and `breath` are normalized to 0 through 1, and `pitch_bend` to -1
through 1. `output` linearly maps that range. A `note` control can instead use
`values = [...]` as a cyclic lookup table. Program changes select the next
configured animation.

The installation's `library_config` is resolved relative to its TOML file.
Lyte validates every selected score output before opening hardware. It discovers
the actual LED count for each string and scales at output time, logging any
authored-layout mismatch. Shutdown requests blackout from each opened string.

`lyte validate` performs Ufor selection and renderer preflight without connecting
to hardware or running an installation. DMX and Art-Net remain available as
separate output primitives; dynamic DMX bindings are not part of this runner.

## Documentation

- `doc/guide.md` explains the current system, its commands, output boundaries,
  and hardware validation limits.
- `doc/handover.md` records the current handover state.

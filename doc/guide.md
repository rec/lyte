# Lyte Guide

Lyte plays Ufor light scores on Twinkly strings, renders them for inspection,
and provides separate primitives for WLED and DMX. Ufor owns portable score
data: layouts, composition, timing, presets, and public scalar parameters.
Lyte owns NumPy rendering, output transport, local services, MIDI mapping, and
the supplied wearable catalogue.

## Start Here

Use a Ufor library configuration to name score roots. With no
`--library-config`, Ufor reads `~/.config/ufor/library.toml`; providing one
replaces that default. Reading a library creates no files.

```sh
# Validate selection and renderer preparation without opening hardware.
lyte show examples:/composition.toml --library-config examples/library.toml

# Create an HTML preview from the same prepared score.
lyte preview examples:/composition.toml preview.html \
  --library-config examples/library.toml

# Play one score on a discovered Twinkly device.
lyte animate examples:/composition.toml \
  --library-config examples/library.toml --duration 10
```

Selectors are Ufor selectors. `--parameters NAME VALUE` supplies public scalar
overrides, and `--output` chooses the score's named light output. Lyte logs all
library diagnostics. A missing or incompatible score, output, parameter, or
wiring order fails during preparation, before hardware opens.

`lyte preview` uses the layout's authored coordinates. `lyte render` produces
an MP4 with a simple grid view for one or more selected scores; it requires
`ffmpeg` on `PATH`.

## Frames and Rendering

A logical light frame is a finite, C-contiguous `numpy.float32` array shaped
`(light_count, component_count)`. Generic Ufor operations work with any
positive component count. Lyte's built-in pixel effects require `red`,
`green`, and `blue` drive components in that order. Scores must use an explicit
Ufor component map when another component contract needs conversion.

Lyte implements every registered Ufor effect with a fixed renderer registry.
Score data cannot import arbitrary Python. Python-defined scores must instead
subclass `lyte.rendering.PythonAnimationScore`, which defines the explicit
state and frame contract.

Each prepared score part has its own mutable state. Rendering the same part
more than once in a logical tick uses its cached result, so a stateful effect
advances once per tick. Separate parts that use the same score have independent
state. Frames are clipped and rounded only when converted to output bytes.

Wiring is a final light-order permutation. Previews and intermediate
composition frames remain in authored logical order. At a physical output,
Lyte rescales frames to the detected LED count and warns if it differs from the
layout count.

## Twinkly Playback

`lyte animate` discovers one Twinkly device when no host is supplied. Playback
authenticates, enters realtime mode, sends UDP frames, probes HTTP health, and
uses bounded recovery after delivery or health failures. Recovery verifies the
device MAC address and refreshes its LED count. Shutdown requests a blackout.

`lyte diagnostic` is read-only device inspection. The other device commands
inspect or change Twinkly brightness, colour, mode, effects, layout, timer,
media, network, and input settings.
These device commands do not turn the lights off after completing their action.

The following physical checks still need the target hardware: visible output,
Wi-Fi recovery, correct string order, fixture addressing, MIDI routing, and
blackout behavior.

## Installations

An installation selects several Twinkly strings, maintains their connections,
and switches named Ufor animations at frame boundaries.

```sh
lyte installation run examples/installation.toml --duration 10
lyte installation install examples/installation.toml
lyte installation status examples/installation.toml
```

The installation TOML describes physical strings under `[twinkly]` and
selectable animations under `[animations.NAME]`. A string selector contains
observed `gestalt` fields such as `product_name`; it never contains an address,
MAC address, or LED count. Lyte discovers devices and requires one unambiguous,
one-to-one assignment. An empty selector can select the one remaining device.

```toml
library_config = "library.toml"
initial_animation = "tree_show"

[twinkly]
left = { product_name = "Dots" }
right = {}

[animations.tree_show]
selector = "examples:/composition.toml"
outputs = { light = "left + right" }
```

Each animation output maps to one physical expression:

- `left` sends to one string.
- `left + right` rescales once to the combined LED count, then partitions the
  result into contiguous string frames.
- `left * right` renders once, then independently rescales that frame for each
  string.

An expression cannot mix `+` and `*`, repeat a string, or leave a selected
string unused. Switching animations prepares fresh renderer state but retains
healthy physical connections. The Reccy RPC endpoint supports `status`,
`select_animation`, `test`, `blackout`, and `stop`.

Installation `fps` controls delivery cadence. Each score retains its declared
timing: slower scores hold their latest frame between ticks, while faster scores
advance through intervening ticks before sending the latest frame. A delayed
delivery catches up to elapsed time. Selection and MIDI note restarts reset the
score timeline.

An optional `[midi]` table reconnects a MIDI input. Animation controls map
note gate, note number, velocity, CC 2 breath, and pitch bend to public Ufor
parameters. An animation may use `activation = "note"` to output black until a
note is held. Program changes queue the next configured animation.

The supplied wearable installation and library are in `patches/`. They provide
36 Ufor presets for a 250-light garment. Its physical map is guessed, so it
must be measured and checked on the assembled garment before performance use.

## Audio-Reactive Effects and Authoring

`lyte.reactivity` is a standalone one-dimensional audio-analysis and frame
processing layer. Callers pass sample blocks to `AudioAnalyzer`; it has no
audio-device, MIDI, output, or geometry dependency. It produces normalized
level, bass, mid, treble, onset, beat, and spectrum features.

The independent reactive effects are scan, spectrum, bass pulse, spotlights,
waterfall, flame, and beat strobe. A live caller creates an effect, analyzes a
sample block, updates the effect state with `update_features()`, then renders.

```sh
lyte author --library-config examples/library.toml --open
```

`lyte author` serves a loopback-only browser editor. It lists Ufor animation
scores and the reactive built-ins under `builtin:`, derives sliders from public
parameters, and regenerates the shared HTML preview after each edit. It does
not edit spatial layouts.

For a Ufor score, the **Composition** panel follows the selected output's
declared operation tree and the parts it references. Selecting an operation
shows its declared fields in the read-only inspector. The **Timeline** shows
each selected `Cues` or `Crossfade` operation as exact rational-second ranges;
overlapping bars show simultaneous cue playback. Direct TOML scores can edit
cue starts and durations or a crossfade duration, then download the validated
result. It is a view and editor for declared Ufor operations, not a generic
keyframe editor.

The **Operation fields** panel edits a direct TOML operation's top-level scalar
fields and downloads a validated result. Nested arrays and tables stay
read-only, preserving their source structure and comments.

The example library was manually checked in the loopback browser on 2026-09-14:
animation selection, reactive parameter sliders, transport pause and seeking,
the composition tree, and cue timeline all worked. Its layouts are
one-dimensional, so a two-dimensional projection still needs a score with a
two-dimensional layout.

Direct TOML animation scores can replace a selected operation with one of the
offered score-aware templates and download the edited source. Lyte validates
and prepares the replacement before download. Source comments survive direct
edits. Ufor rejects unknown score fields before authoring, so there are no
unknown fields to round-trip. Presets and Python scores remain read-only.

Use **Download TOML preset** to save the selected Ufor score's current public
parameter values as a new `kind = "preset"` file. The browser downloads the
file only after Lyte validates and prepares it; source scores are never
overwritten. Reactive built-ins remain preview-only.

## WLED Interchange

WLED support has three separate boundaries. It does not claim that WLED's
native effects and Lyte effects are interchangeable.

```sh
lyte wled import snapshot-input --output wled-snapshot.json
lyte wled list wled-snapshot.json
lyte wled export wled-snapshot.json --output presets.json
lyte wled translate wled-snapshot.json --output generated-scores
```

Import requires `presets.json`, `eff.json`, `fxdata.json`, `pal.json`, and
`info.json`, or a `metadata.json` that contains missing metadata responses. It
creates a portable snapshot with raw source data and source hashes, while
removing network identity fields such as host, IP, MAC, Wi-Fi name, and token.
Export writes the original native `presets.json` losslessly.

Translation is deliberately limited to one-segment presets for declared effect
mappings: Solid, Breathe, Chase, Chase Rainbow, Candle, Color Wipe, Comet,
Rainbow, Scan, and Twinkle. It creates independent Ufor score files and a
manifest. Unsupported presets remain native data and receive a reason in that
manifest.

`WledDdpOutput` is a transient output primitive. Given a host and a discovered
LED count, it rescales RGB frames and sends chunked DDP packets to port 4048.
It does not discover devices or persist network identity, and it is not yet a
target in the installation runner.

## DMX and Art-Net

`lyte.dmx` describes one contiguous channel range in one universe. Categories
cover brightness, RGB, white, chase speed, pattern, strobe, pan, tilt, colour
wheel, gobo, and named raw channels. The encoder creates C-contiguous,
512-byte DMX universe frames.

`lyte.artnet.ArtNetDriver` sends those frames as ArtDmx UDP packets and can
black out specified universes. DMX and Art-Net are independent output
primitives; installation animation selection currently controls Twinkly only.

## What the Tests Establish

The test suite covers score preparation and diagnostics, renderer behavior,
composition and state ownership, parameter updates, wiring, previews, reactive
processing, Twinkly recovery, installation selection and output expressions,
MIDI mapping, WLED snapshots and DDP packet bytes, plus DMX and Art-Net
encoding. It cannot establish the physical checks listed above.

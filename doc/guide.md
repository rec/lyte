# lyte Guide

lyte plays uFor light scores on Twinkly and WLED strings, renders them for
inspection, and provides separate primitives for DMX. uFor owns portable score
data: layouts, composition, timing, presets, and public scalar parameters.
lyte owns NumPy rendering, output transport, local services, MIDI mapping, and
the supplied wearable catalogue.

## Audio-driven scores

The portable `audio_spectrum` effect uses the existing spectrum analyzer. Try
`examples/audio/spectrum.toml` with an 8, 16, 24 or 32-bit integer PCM WAV file:

```sh
lyte author --library-config examples/audio/library.toml --audio song.wav
lyte preview audio:/spectrum.toml --library-config examples/audio/library.toml \
  --audio song.wav --output spectrum.html
lyte render audio:/spectrum.toml --library-config examples/audio/library.toml \
  --audio song.wav --projection xy
```

These commands generate lighting visuals, without playing or embedding a
soundtrack. Audio-backed scores run to audio EOF, overriding `--duration`.
The editor disables looping for these previews; you can turn it on explicitly.
Standalone HTML holds its final frame. Movies end at the audio duration.

Analysis starts at sample zero. At root score tick `k`, the analyzer receives
samples from `floor(k * sample_rate / fps)` to
`floor((k + 1) * sample_rate / fps)`, with the end excluded. Channels are averaged
to mono. The last window is zero-padded; there is no extra tail or silent loop.
All audio-reactive parts receive the root timeline's observation, including
parts activated by later cues. Frame boundaries use the exact rational score
rate. Analysis is repeated from its initial state for each preview or export.
WAV data is read a window at a time; analyzed features are retained in memory.
HTML and editor previews retain their 10000-frame/32 MiB frame-data limits.

uFor declares normalized audio features and spectrum effect settings. Scores
contain no audio path or device I/O; select the WAV again when reopening a
score. The existing built-in reactive demonstrations still use synthetic inputs.
This milestone makes spectrum scores editable and exportable; other reactive
effects and live audio input remain future work. Physical playback rejects
audio-driven scores before opening devices.

## Start Here

Use a uFor library configuration to name score roots. With no
`--library-config`, uFor reads `~/.config/ufor/library.toml`; providing one
replaces that default. Reading a library creates no files.

```sh
# Validate selection and renderer preparation without opening hardware.
lyte validate examples:/composition.toml --library-config examples/library.toml

# Create an HTML preview from the same prepared score.
lyte preview examples:/composition.toml --output preview.html \
  --library-config examples/library.toml

# Play one score on a discovered Twinkly device.
lyte animate examples:/composition.toml \
  --library-config examples/library.toml --duration 10
```

Composition source selections use `part` and `output`, for example
`source = { part = "intro", output = "light" }`. Older scores using `name`
in those selections must change it to `part`. Python score references use
`ufor.interface.ScoreReference`.

Selectors are uFor selectors. `--parameters NAME VALUE` supplies public scalar
overrides, and `--light-output` chooses the score's named light output. lyte logs all
library diagnostics. A missing or incompatible score, output, parameter, or
wiring order fails during preparation, before hardware opens.

`lyte preview` uses the layout's authored coordinates. `lyte render` produces
an MP4 for one or more selected scores; it requires `ffmpeg` on `PATH`.
Movies default to grid mode. Use `--projection xy` (or `xz`, `yz`) for authored
positions, with `--width`, `--height`, `--zoom`, and `--led-size`. HTML previews
use `--plane xy` (or `xz`, `yz`) with the same zoom and light-size semantics.
At equal canvas dimensions, framing and orientation match; positive vertical
coordinates point down. Light size multiplies a radius of the greater of three
pixels and 1/140 of the shorter canvas dimension. Movie coordinates round to
pixels, and movie dimensions round up to even numbers for the encoder.
Use `--background-color '#050506'` for movies to match the default preview
background; HTML uses `--background '#rrggbb'`. Movie grid layout, diameter,
and padding retain their existing meanings.
Movie export rejects colliding filenames and existing destinations before
starting the batch. Use a fresh output directory to retain previous exports.
Failed exports discard their temporary movies; final filenames appear only
after encoding succeeds.

## Frames and Rendering

`lyte benchmark aurora --library-config examples/library.toml --duration 10`
reports score rendering time as JSON: frame count, declared rate, light count,
mean/maximum seconds, and frames exceeding one score-frame budget. It renders
offline without encoding, sleeping, or opening devices. Initialization is excluded.
An isolated score benchmark does not include mapping, transport, or the combined
cost of other installation outputs.

Installation status includes cumulative render costs by animation/output,
including catch-up ticks beyond the first tick needed for a delivery. These
counters survive note restarts and reselection during the process lifetime.
Delivery diagnostics separately report scheduled and actual intervals, maximum
lateness, total output time, and failed sends. Costs are aggregates, so normal
playback emits no per-frame diagnostic log. The scheduler and logical score ticks
are unchanged; diagnostics never skip work to improve reported performance.

A logical light frame is a finite, C-contiguous `numpy.float32` array shaped
`(light_count, component_count)`. Generic uFor operations work with any
positive component count. lyte's built-in pixel effects require `red`,
`green`, and `blue` drive components in that order. Scores must use an explicit
uFor component map when another component contract needs conversion.

lyte implements every registered uFor effect with a fixed renderer registry.
Score data cannot import arbitrary Python. Python-defined scores must instead
subclass `lyte.rendering.PythonAnimationScore`, which defines the explicit
state and frame contract.

Each prepared score part has its own mutable state. Rendering the same part
more than once in a logical tick uses its cached result, so a stateful effect
advances once per tick. Separate parts that use the same score have independent
state. Frames are clipped and rounded only when converted to output bytes.

Wiring is a final light-order permutation. Previews and intermediate
composition frames remain in authored logical order. At a physical output,
lyte rescales frames to the detected LED count and warns if it differs from the
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

`lyte panel` opens a local operator page on port 8767 for the running installation.
It uses the existing lyte reccy identity and RPC socket; it does not start another
installation daemon. Active/queued animation, MIDI connection, blackout, tests,
per-string health, and timing diagnostics come from service status, refreshed
every second. Selection, test, blackout, and stop affect real outputs. Disconnection
disables controls and labels the retained display as stale. Reconnection refreshes
status without retrying commands, and rejected-command messages remain until
cleared. Use `--no-open` to serve the page without opening a browser.

The panel and rehearsal have **Fade (s)** and **Master (%)** controls. Selection
crossfades linearly after both scores have rendered and mapped to the physical
strings. Zero seconds cuts immediately. During a normal fade, both animations
receive MIDI and obey their own note gates. Selecting again freezes the last
displayed blend and fades from it, avoiding a jump or an accumulating chain of
renderers. That frozen snapshot no longer responds to MIDI; the incoming score
does. Master level scales the final output, including test output, without
changing score parameters. Blackout cancels the fade immediately at the next
delivery boundary. A timed selection out of blackout fades from black.

RPC selection accepts `select_animation(name=..., duration=...)`, with duration
defaulting to zero. `master_level(level=...)` accepts 0–1. MIDI program changes
retain immediate selection. Tests temporarily override the visible output while
the fade's clock continues; selecting during a test fades from its displayed
frame. Device connections stay open throughout selection and fading.

For software-only rehearsal, run:

```sh
lyte rehearse examples/installation.toml --string-counts left 125 right 125
```

Supply every Twinkly string's simulated light count. WLED strings use their
configured `led_count`; do not repeat them in `--string-counts`. Twinkly counts are rehearsal
inputs, not production device selectors. The loopback browser opens on port 8766
(`--no-open` leaves it closed). It displays each string separately and offers
animation selection, step/play/pause, test override, blackout, and synthetic MIDI
when MIDI is configured. Controls take effect at the next simulated delivery tick.
Playback uses the live installation's shared state, mappings, channel ownership,
scaling, concatenation, and mirroring. Browser delays slow the simulated clock;
they do not skip score ticks. No installation daemon, hardware discovery, MIDI
port, or device output starts. This checks software behavior, not physical readiness.

Record a rehearsal from its start with `--record-input performance.jsonl`.
Capture includes synthetic MIDI and accepted operator commands, including fades,
master level, tests, and blackout. Stop the rehearsal server normally to seal the
recording. Existing files are never overwritten. A recording failure stops capture
and is shown in the browser while playback continues; recordings with missing or
damaged data are rejected.

Replay offline with:

```sh
lyte rehearse examples/installation.toml --replay performance.jsonl
```

Replay uses the recorded string counts and delivery clock; omit `--string-counts`.
Inputs come from the recording, so operator and MIDI controls are disabled.
Configuration or score-source differences appear as warnings, including changed
declared seeds. Identical deterministic scores reproduce the captured frames.
The journal stores a configuration/score header, then each delivery's timestamp
and ordered inputs using uFor MIDI events and reccy command requests. MIDI event
ticks count delivery frames; ordinals retain input order. It records consumption
at delivery boundaries, not raw device arrival times. It does not capture output
packets or make physical playback available.

For live capture, use `lyte installation run examples/installation.toml
--record-input performance.jsonl`. The option applies to `run`, not service
installation. Capture starts with the installation, including MIDI and operator
commands received during output startup. The normal MIDI/selection/render paths
are shared with rehearsal. Existing destinations or failures opening, serializing,
writing, flushing, or closing the journal disable recording, not lighting. The
error remains visible in installation status and the operator panel; failed
capture stops buffering and does not retry disk writes. Use a fresh path for the
next run. Status-file write failures likewise leave playback and in-memory RPC
status available. Recoverable frame-render errors keep the loop running and leave
the previous physical frame displayed until rendering recovers or another
animation is selected. Explicit stop and interruption still stop playback.

An installation drives Twinkly and WLED strings and switches named uFor
animations at frame boundaries. Both transports share selection, fades, master
level, test patterns, blackout, recording and status.

`lyte installation` is the sole service command. The legacy wearable daemon
has been retired; `lyte patch` and the wearable uFor catalogue remain available.
On machines with an older wearable service installed, stop and uninstall that
service with `lyte installation stop` and `lyte installation uninstall`, then
install the chosen installation configuration. Old service definitions that
invoke `lyte daemon` must be replaced; they are not migrated automatically.

Set `startup_timeout = 30` in the installation TOML to bound device discovery
and identification (30 seconds by default). `discovery_timeout` bounds each
individual scan; identification retries and waits share the overall discovery
deadline. Missing devices are retried until that deadline; ambiguous assignments
fail immediately. Ctrl-C interrupts foreground discovery. Runtime RPC is not
available until discovery completes.

Authentication and output setup retain their existing bounded retries and are
outside the discovery timeout. `--duration` measures playback after outputs are
ready, so discovery and setup do not consume the requested playing time.

```sh
lyte installation run examples/installation.toml --duration 10
lyte installation install examples/installation.toml
lyte installation status examples/installation.toml
```

The installation TOML describes Twinkly strings under `[twinkly]`, WLED targets
under `[wled]`, and selectable animations under `[animations.NAME]`. A Twinkly
selector contains
observed `gestalt` fields such as `product_name`; it never contains an address,
MAC address, or LED count. lyte discovers devices and requires one unambiguous,
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
healthy physical connections. The reccy RPC endpoint supports `status`,
`select_animation`, `test`, `blackout`, and `stop`.

A light test temporarily overrides the display, then resumes the selected
animation at its elapsed score time. `blackout` cancels queued selection and
tests, keeps the service running, and sends black frames until an animation is
selected. Status reports `blackout`; tests are rejected while it is active.
Selecting an animation also cancels an active test. Only `stop` terminates
playback and closes the outputs.

Installation `fps` controls delivery cadence. Each score retains its declared
timing: slower scores hold their latest frame between ticks, while faster scores
advance through intervening ticks before sending the latest frame. A delayed
delivery catches up to elapsed time. Selection and MIDI note restarts reset the
score timeline.

An optional `[midi]` table reconnects a MIDI input. Animation controls map
note gate, note number, velocity, CC 2 breath, and pitch bend to public uFor
parameters. An animation may use `activation = "note"` to output black until a
note is held. Program changes queue the next configured animation.
Each program-change message advances the queued selection; its program number
is ignored. The latest note-on owns the active note, even across channels.
Releases, breath, and pitch bend only affect it when their channel matches.
Preparation rejects non-finite or out-of-range mapped values and unsupported
live parameter changes before discovering devices. Built-in effect parameters
that are construction-only cannot be mapped to live MIDI controls.

The supplied wearable installation and library are in `patches/`. They provide
36 uFor presets for a 250-light garment. Its physical map is guessed, so it
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

`lyte author` serves a loopback-only browser editor. It lists uFor animation
scores and the reactive built-ins under `builtin:`. Search names, selectors,
and tags, or filter by library and effect family. Entries use their canonical
library paths, so duplicate names remain distinct. Blocked entries display
field/dependency diagnostics and links to dependencies and referring scores.
The selected score shows its source type, rate, light count, outputs, and
parameter targets, bounds, defaults, and units. **Render thumbnail** renders
only the selected score's initial frame on request, with its existing seed.
The editor derives sliders from public parameters and regenerates the shared
HTML preview after each edit. It does
not edit spatial layouts.

Slider changes are coalesced, with one preview request at a time per browser.
The server renders one preview at a time; other tabs receive a busy message.
Authoring and standalone HTML previews allow at most 10000 frames and 32 MiB
of raw frame data. Reduce duration or layout size if a preview exceeds either
limit. Base64 encoding and browser copies require additional memory.

For a uFor score, the **Composition** panel follows the selected output's
declared operation tree and the parts it references. Selecting an operation
shows its declared fields in the read-only inspector. The **Timeline** shows
each selected `Cues` or `Crossfade` operation as exact rational-second ranges;
overlapping bars show simultaneous cue playback. Direct TOML scores can edit
cue starts and durations or a crossfade duration, then apply and download the validated
result. It is a view and editor for declared uFor operations, not a generic
keyframe editor.

**Composition structure** edits named parts and the selected score's cues,
mix, placement, gain, reversal, or crossfade. Choose **Review composition
changes** to validate a draft and inspect its diff before applying it. Moving
cue contents exchanges references between the existing time slots, preserving
starts, durations, gaps, and overlaps. Timing fields remain explicitly editable;
adding or removing a slot never shifts the other slots. Shared source edits
affect every use, and the panel lists referring scores. Rejected drafts leave
the working score and history unchanged.

The **Operation fields** panel edits a direct TOML operation's top-level scalar
fields and applies and downloads a validated result. Nested arrays and tables stay
read-only, preserving their source structure and comments. **Colours and
palettes** separately supports Aurora and ExpandingRipples palettes, ColorFill
and ColorChase colours, and RGB drive Fill values. Swatches and numeric channels
show their units: bytes are 0–255; normalized drive uses 1 as full scale.
Out-of-range normalized values are preserved numerically while swatches clip
their display. Palettes support adding, removing, and reordering colours.
Unsupported nested fields remain read-only.

The example library was manually checked in the loopback browser on 2026-09-14:
animation selection, reactive parameter sliders, transport pause and seeking,
the composition tree, and cue timeline all worked. On 2026-09-16, the nine pixels in `examples/scores/grid.toml` were
visually verified as three distinct rows and columns in the authoring browser.
The editor supports XY, XZ, and YZ projections, zoom, fit, light names and
logical indexes. Click a light to select it. For direct TOML scores, edit the
coordinate table or enable dragging to move lights in the visible plane; hidden
coordinates remain unchanged. Apply validates and downloads the layout through
the same undo history. Wiring remains separate. **Download standalone HTML
preview** exports the current working animation and parameter values, with the
selected projection, zoom, light size, and background. Apply a pending layout
draft first. This is a visual artifact, not editable source, and does not mark
source edits as downloaded.

The editor shows each selected score's library path and source type. **Undo**
and **Redo** restore accepted document edits across the session, including
referenced scores and comments. **Session edits** lists documents that differ
from their original text. A new accepted edit clears redo; preview playback
and parameter sliders do not enter document history.

Direct TOML animation scores can replace a selected operation with one of the
offered score-aware templates and download the edited source. lyte validates
and prepares the replacement before download. Edits accumulate in the running editor, and the composition tree and preview
refresh after each accepted edit. Source comments survive direct edits. uFor rejects unknown score fields before authoring, so there are no
unknown fields to round-trip. Presets and Python scores remain read-only.

Use **Download TOML preset** to save the selected uFor score's current public
parameter values as a new `kind = "preset"` file. The browser downloads the
file only after lyte validates and prepares it; source scores are never
overwritten. Download every changed score to retain the working document;
**Download all edits (ZIP)** offers all changed TOML files together, under
library-name directories with their relative source paths preserved. The list
shows which current revisions this browser has offered for download; it cannot
verify that a download was saved. Closing with unoffered changes prompts a warning.
The ZIP is a set of edits to your libraries, not a standalone library bundle.
Restarting the editor discards its in-memory changes. Presets referring to edited
scores require those edited score files as well. Reactive built-ins remain preview-only.

## WLED Interchange

WLED support has three separate boundaries. It does not claim that WLED's
native effects and lyte effects are interchangeable.

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
Rainbow, Scan, and Twinkle. It creates independent uFor score files and a
manifest. Unsupported presets remain native data and receive a reason in that
manifest.

Installation targets use an explicit hostname or IPv4 address and light count:

```toml
[wled.right]
host = "wled.local"
led_count = 60
```

Use a bare hostname or address, without a URL scheme or port. The destination
is UDP port 4048. Counts are never queried from WLED; update the configuration
when the physical layout changes. Output names must be unique across transports,
and each animation must bind every output. Concatenation (`left + right`) and
mirroring (`left * right`) work across transports. WLED-only installations omit
`[twinkly]` and perform no discovery. Mixed installations retain Twinkly's
existing discovery and startup requirements.

`examples/installation-wled.toml` demonstrates a mixed installation. Rehearse
it without devices with `lyte rehearse examples/installation-wled.toml
--string-counts left 125`. Set the actual WLED host/count and Twinkly selector
before physical playback with `lyte installation run`.

The runner uses `WledDdpOutput` to send chunked RGB frames. Status displays
`ready` before the first attempt and `sending (unconfirmed)` after a successful
UDP send. This is not a device-health check: DDP has no acknowledgements, so an
unplugged device may still appear to be sending successfully. Local send errors
increment failure counters; other outputs continue, and the next scheduled frame
tries again without queuing old frames. Socket acquisition is also attempted on
a later frame if it fails. Socket operations use the installation `timeout`;
operating-system hostname resolution has its own timing.

Blackout sends zero RGB frames while the runner remains active. Shutdown attempts
one final zero frame before closing the socket. Delivery is not guaranteed; WLED
may resume its local preset when its realtime timeout expires. Physical checks
of selection, unplug/replug and blackout remain necessary on the actual devices.

## DMX and Art-Net

`lyte.dmx` describes one contiguous channel range in one universe. Categories
cover brightness, RGB, white, chase speed, pattern, strobe, pan, tilt, colour
wheel, gobo, and named raw channels. The encoder creates C-contiguous,
512-byte DMX universe frames.

`lyte.artnet.ArtNetDriver` sends those frames as ArtDmx UDP packets and can
black out specified universes. DMX and Art-Net are independent output
primitives; installation animation selection currently controls Twinkly and WLED pixels.

## What the Tests Establish

The test suite covers score preparation and diagnostics, renderer behavior,
composition and state ownership, parameter updates, wiring, previews, reactive
processing, Twinkly recovery, installation selection and output expressions,
MIDI mapping, WLED snapshots and DDP packet bytes, plus DMX and Art-Net
encoding. It cannot establish the physical checks listed above.

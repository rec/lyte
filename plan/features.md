# Feature suggestions

Reviewed against the current code and guide on 2026-09-16. These are proposals,
not implementation commitments. Choose a milestone before changing code or
introducing new dependencies. The order below favors useful authoring and show
rehearsal features over additional hardware or wearable-specific work.

## Recommended starting order

| Order | Feature | Why first | Relative size |
| --- | --- | --- | --- |
| 1 | Undo, redo, and a list of changed scores | Makes cumulative editing easier to trust | Small |
| 2 | Download all edited scores together | Prevents losing changes in referenced parts | Small |
| 3 | Composition structure editing | Makes the editor useful for creating arrangements | Large |
| 4 | Library browser and actionable diagnostics | Makes larger libraries easier to navigate | Medium |
| 5 | Installation rehearsal without hardware | Checks a whole show before connecting devices | Medium |
| 6 | Live installation controls and transitions | Makes an installation easier to operate during a show | Large |

Sizes describe relative implementation scope, not delivery estimates. Features
1 and 2 make a useful first milestone without changing the score format or
hardware runtime. Later suggestions can be selected independently except where
a dependency is stated.

## Editor

### 1. Undo, redo, and changed-score tracking

**Completed 2026-09-16.** Session-wide document history, changed-score list, and
source/editability labels are implemented. Tests cover referenced-score edits,
exact comment restoration, rejected edits, redo branches, and preview restoration.

Edits already accumulate in memory, but there is no way to reverse an accepted
edit or see the complete set of changed documents.

First version:

- Keep undo and redo history for accepted document edits across the session.
  One Apply action is one history entry, including an operation replacement.
- Show changed scores, the selected score's source path, and whether each score
  is editable. Distinguish direct TOML, presets, and Python-defined scores.
- Restore the catalogue, inspector, and preview together when undoing or redoing.
  A rejected edit adds no history; a new accepted edit clears the redo branch.
- Keep preview playhead and transient parameter-slider movement outside document
  history. Saved preset parameters remain a separate, explicit action.

Complete when edits to two referenced scores can be undone and redone in order,
including their comments, without touching the source files. Returning to the
original document removes its changed marker.

### 2. Download all edited scores together

A composition may depend on several edited files. Downloading just its root or
a preset does not preserve changes to those dependencies.

First version:

- Add one action that downloads every changed TOML score in a ZIP, organized by
  library name and relative source path so equal filenames remain distinct.
- Show the included files before download. Explain that this is a set of edits
  to the loaded libraries, not a standalone copy of every library dependency.
- Retain individual downloads. Mark which revision was last offered for download,
  without claiming the browser has saved it successfully.
- Warn before closing a page with changes not yet offered for download. Keep
  original files unchanged; direct filesystem saving is a separate decision.

Complete when edits to a root and two referenced parts are all included with
comments intact, and the files can replace the corresponding originals in a
copy of the library and pass validation. Build on feature 1's changed-score list.

### 3. Composition structure editing

The editor can inspect composition and change timing or scalar fields, but
cannot yet conveniently build a composition from existing scores.

First version:

- Add, remove, and reorder cues; choose a referenced score and its light output.
- Add or remove parts in the selected direct TOML composition, with explicit
  names and references using the existing uFor format.
- Edit placement, mix weights, gain, and reversal through controls for the
  operations uFor already supports.
- Show the resulting change before applying it. Explain incompatible component
  contracts, missing outputs, and dependency cycles at the affected control.
- Make shared references visible: editing a source part changes every use of
  that source. Do not silently clone it to make an edit appear local.

Complete when a user can build a two-score sequence and a simultaneous mix,
preview them, then download and reload the same arrangements. Use features 1
and 2; do not introduce a second composition model or a generic keyframe system.

### 4. Library browser and actionable diagnostics

Replace the single animation list with navigation that remains useful as the
library grows.

First version:

- Search by name, selector, and tag; filter by library and effect family.
- Show blocked entries as well as ready entries, with the dependency or field
  diagnostic that explains why an entry cannot be prepared.
- Show public parameter descriptions and bounds, declared rate, light count,
  output names, and the scores that reference the selected entry.
- Generate thumbnails only on request or for visible entries, using a fixed
  preview time and the score's existing seed. Avoid rendering the entire library
  just to populate the browser.

Complete when a broken dependency can be traced to its source from the browser
and a score can be selected unambiguously even when several share a title.

### 5. Palette and nested-field editors

Scalar controls leave common edits, especially colours and palettes, in TOML.

First version:

- Provide colour swatches with numeric component values for known RGB fields.
- Add, remove, and reorder palette stops where the existing effect schema
  permits it, preserving comments on untouched data.
- Show units and distinguish normalized values from byte-valued components.
  A swatch must not silently change the score's numeric interpretation.
- Start with a small, named set of supported field shapes. Unsupported nested
  structures remain visible and read-only.

Complete when a palette can be changed and reordered, then reloaded with the
same values and appearance. Reuse feature 1's edit history.

### 6. Spatial layout inspection and editing

Current previews use XY projection and ignore Z; the editor does not edit layouts.

First version: selectable XY, XZ, and YZ views with axis labels, fit-to-layout,
zoom, light names, and logical indexes. Add a coordinate table for direct TOML
layouts, then selection and dragging in the chosen plane. Preserve the hidden
coordinate when editing a projection.

Complete when a 3D fixture can be inspected in all three planes, one coordinate
can be edited without changing the others, and the resulting layout reloads.
Keep wiring separate from authored positions. Perspective orbit controls and
camera-based capture can wait until the simpler views are useful.

## Rendering and rehearsal

### 7. Matching spatial previews and movie exports

HTML previews show authored coordinates, while MP4 export currently arranges
lights in a grid. A movie therefore may not communicate the intended layout.

First version: offer authored-coordinate projection in movie export, alongside
the existing grid mode, with the same axes, framing, background, and light size
semantics used by preview. Allow an editor user to download a standalone HTML
preview of the current working composition, clearly separating that visual
artifact from editable source downloads.

Complete when an asymmetric layout has the same orientation and relative
positions in the editor, HTML, and MP4. All paths must use the shared prepared
score renderer. Preserve export collision checks and existing preview limits.

### 8. Installation rehearsal without hardware

Preview an installation's output bindings, not just one score output.

First version:

- Load installation TOML without discovery, service startup, or network output.
- Supply simulated string counts explicitly for rehearsal; do not add them to
  the production Twinkly selectors.
- Display named strings separately, including concatenation, mirroring, and
  output scaling, and select among configured animations.
- Provide synthetic note, breath, velocity, and pitch-bend inputs using the
  installation's actual mappings and channel-ownership rules.

Complete when a two-string installation can be rehearsed, including differing
score and delivery rates, note restart, test override, and blackout. Use the
runtime's existing frame distribution and control logic rather than copying it
into the browser. This demonstrates software behavior, not physical readiness.

### 9. Render cost and timing diagnostics

Help users find effects or compositions that cannot keep up at the chosen rate.

First version: report render time per animation, scheduled versus actual frame
intervals, catch-up ticks, and output failures. Add an offline benchmark for a
selected score and duration, with light count and frame rate included in its
report. Separate score rendering cost from encoding and device delivery.

Complete when an intentionally slow renderer produces an understandable report
and normal playback does not need verbose per-frame logging. Do not change
stateful catch-up behavior or discard logical ticks as part of this feature.

## Live operation and integration

### 10. Installation control panel

Provide a small operator view for the existing installation service, separate
from the hardware-free authoring page.

First version: display active and queued animation, MIDI connection state,
blackout, and per-string health; expose the existing selection, test, blackout,
and stop commands. Distinguish a disconnected panel from a healthy installation
and retain visible errors when a command is rejected.

Complete when the panel accurately reflects commands sent by another client and
a reconnect refreshes state without replaying old commands. Use the existing
reccy service identity and RPC methods; do not add another daemon. Keep the
initial interface local to the machine operating the installation.

### 11. Smooth animation transitions and a master level

Animation selection currently starts fresh state at a frame boundary. Offer
intentional transitions between named installation animations.

First version: a linear crossfade with an explicit duration, plus a master output
level. Crossfade after each animation has been rendered and mapped to the same
physical outputs so different layouts and rates remain well-defined. Zero
transition duration retains an immediate cut.

Before implementation, choose the policy for a new selection during a fade:
queue it, restart from the displayed blend, or finish the current transition.
Also define how note-gated animations behave during a transition. Blackout must
remain immediate, and master level must not modify source parameters.

Complete when endpoints are exact, interrupted selection follows the chosen
policy, connections stay open, and render-cost diagnostics account for rendering
two animations. Rehearsal support from feature 8 would make this easier to test.

### 12. Recorded control input for repeatable rehearsal

Capture and replay MIDI performance input to reproduce an animation's behavior
without performing the same gestures again.

First version: record timestamps and MIDI messages from the existing input path;
replay a selected recording against a chosen score or installation in offline
rehearsal. Record which configuration and seeds were used, and report when the
current configuration differs. Physical playback of a recording is a separate,
explicit action.

Complete when replay yields the same frame sequence as the captured input for
a deterministic score, including channel ownership and note releases. Reuse a
suitable existing format or shared facility after checking reccy and uFor;
do not invent a parallel event format before that review.

### 13. Audio-driven scores

The audio analyzer and reactive effects exist, but the editor's built-ins use
synthetic features and remain preview-only.

First version: analyze a chosen audio file and feed its timed features into a
previewable, exportable animation. Start offline so effect behavior is repeatable
before adding live audio-device selection and reconnection.

This needs an explicit ownership decision: portable feature/control declarations
belong in uFor, while sample acquisition and analysis integration belong in the
appropriate runtime. Review existing recs facilities before adding a second
audio capture path. Define audio-to-score timing and end-of-file behavior.

Complete when the same audio file drives matching preview and exported frames,
and a saved score describes its required controls without embedding device I/O.

### 14. WLED and DMX installation outputs

Extend the sole installation runner to use the existing WLED DDP and Art-Net
primitives. This is architectural work, not just adding another command.

First milestone: one WLED target beside a Twinkly string, sharing selection,
master level, blackout, and status. Decide how WLED devices are identified and
how their light counts are obtained before defining configuration fields.

A later DMX milestone should bind declared fixture channels to controls, detect
address overlap, and compose one universe frame before sending it. Define
fixture-specific blackout behavior; zeroing every channel is not necessarily an
appropriate stopped state for moving fixtures.

Complete each transport separately with packet-level checks and a physical
rehearsal covering selection, disconnection, and blackout. Avoid a speculative
plugin framework or promises of network-wide frame synchronization.

### 15. Rehearsal cue list and showCo integration

Operate a named sequence of installation looks, with explicit Go, Back, and
current/next cue state. This is useful for shows that need repeatable progression
rather than cycling every program-change message.

Start with manual cue advancement and existing animation selection. Timed cues,
transition durations, and synchronization to other show actions can follow.
Choose the owner first: showCo should coordinate a show across applications;
lyte should own lighting execution and expose the required status and controls.
Do not create competing cue schedulers in both systems.

Complete when a short show can be rehearsed forwards and backwards and a client
reconnect displays the actual current cue without advancing it. Shared clock or
timecode support should follow a concrete synchronization requirement.

## Later possibilities

- Device-specific brightness and colour calibration at the physical output
  boundary, with a deliberate calibrated-preview mode. Define units and measure
  hardware before treating an estimated brightness limit as a power limit.
- Additional geometry-aware effects for measured installations: radial waves,
  height gradients, and nearest-neighbour propagation. Use declared coordinates,
  not guessed relationships between LED indexes.
- A before/after comparison view with a fixed playhead and seed, useful when
  tuning palettes or rendering changes.

The region-effect ideas in [new-animations.md](new-animations.md) remain a
separate catalogue. Wearable-specific additions are lower priority until there
is a scheduled use and measured hardware. Existing mixes, reversal, cues, and
crossfades should be tried before proposing new effect implementations.

## Additional work beyond the prompt

None. This document proposes features only; it does not implement them, change
dependencies, or authorize the architectural decisions called out above.

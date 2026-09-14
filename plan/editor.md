# Animation Editor

## Goal

Turn `lyte author` into a local visual editor for Ufor animation scores. It
must edit the same declared score model that Lyte prepares and previews: no
second animation format, no hidden renderer state, and no implicit hardware
output.

The editor is for authors, not show operators. Its job is to make a score
understandable, adjustable, and safe to inspect before a deliberate playback
or installation selection.

## Product Shape

Keep the existing loopback-only browser application. It already loads a Ufor
library, obtains parameter contracts, and renders frames with the production
Lyte pipeline. A browser keeps it portable and makes no desktop framework or
new dependency necessary.

The completed editor has four coordinated views:

1. **Visualizer.** Draw authored light coordinates and the selected preview
   frame. It falls back to a horizontal logical strip when a layout has only
   one coordinate. Transport controls play, pause, step, loop, and seek the
   finite preview frame sequence.
2. **Composition.** Show the selected output as an editable Ufor operation
   tree: effects, fills, sources, placements, mixes, reverses, gains,
   crossfades, cues, and component maps. Selecting a node selects its
   inspector.
3. **Inspector.** Show the selected score or operation's declared values.
   Numeric controls use the actual Ufor parameter contracts, including limits,
   defaults, and units. Invalid edits remain visible with their exact
   validation diagnostic and never replace the last valid preview.
4. **Cue editor.** Represent Ufor cues and crossfades on a timeline. It edits
   their existing exact rational timing rather than inventing a generic
   keyframe format.

The browser receives only a catalog and prepared-preview responses. The server
continues to own library loading, Ufor validation, and NumPy rendering.

## First Useful Version

Improve the existing parameter-authoring page without changing score files:

- keep the animation selector and contract-derived parameter sliders;
- redraw LEDs at the score's authored two-dimensional coordinates;
- provide play/pause, previous-frame, next-frame, loop, and frame scrubber
  controls;
- render the selected frame immediately after a parameter change;
- display the selected animation title, frame number, frame count, and FPS;
- preserve the loopback-only server and hardware-free preview boundary.

This is useful before persistence exists because authors can inspect the exact
prepared score and tune public parameters with deterministic, frame-level
feedback. It does not claim to edit score structure or save a score.

## Score Editing and Saving

After the first version, add a deliberate save workflow. It must write a new
human-readable Ufor TOML file, never overwrite a source score by default, and
make the destination explicit in the UI. The server validates the candidate
document by loading and preparing it before reporting success.

The save model should preserve unknown source fields where possible. If Ufor
does not expose a lossless TOML source representation, the editor should first
save a small parameter-preset document rather than manufacture incomplete
score TOML. That decision must be based on the available Ufor API and covered
by a round-trip fixture.

Built-in reactive effects remain preview-only until they have a declared Ufor
score representation. They must not be serialized as fake Ufor effects.

## Composition Editing

Add structure editing only after saving has a lossless representation:

- expose one selected output and its composition tree;
- add and remove nodes through score-aware templates;
- permit only valid named references, output names, component contracts, and
  layout regions;
- apply every proposed edit through Ufor validation, retaining the last valid
  tree and preview on failure;
- show diagnostics beside the field or node that caused them.

The editor should model Ufor operations directly. A separate free-form node
graph would duplicate semantics and make round-tripping harder.

## Timeline Editing

Cue and crossfade editing follows composition editing. The timeline is a view
of existing `Cues` and `Crossfade` operations, not the primary representation
of every animation. It displays exact rational positions and durations while
allowing conventional user-facing units such as seconds and beats when the
score's timebase makes them unambiguous.

## Explicit Boundaries

- The editor never opens a Twinkly, WLED, DMX, or Art-Net output.
- Hardware playback remains a separate `lyte animate` or installation action.
- Wiring is never applied in the visualizer; it is a physical output concern.
- The editor does not infer component conversion, geometry, regions, or effect
  behavior that the score does not declare.
- The editor must not expose arbitrary Python imports or execute score text
  supplied by the browser.

## Validation

Add focused tests for:

1. an authored two-dimensional layout reaching the preview response unchanged;
2. the browser document containing transport controls, coordinate projection,
   and contract-derived controls;
3. parameter edits returning prepared frames with the selected values;
4. malformed preview requests returning a concise JSON diagnostic;
5. later save and structure-edit round trips, including unknown-field retention
   and rejection that leaves the previous score usable.

Manual validation for the first version: open `lyte author`, select a score,
move a parameter slider, pause and seek a frame, and confirm that a ring or
other non-strip layout is drawn according to its authored coordinates.

## Remaining Work After the First Useful Version

1. Investigate a lossless Ufor TOML save API and add explicit save-as.
2. Add a composition tree and read-only operation inspector.
3. Add validated structural editing and save round trips.
4. Add cue and crossfade timeline editing.
5. Add optional, deliberate handoff from a saved score to preview rendering or
   an installation selection, without embedding hardware control in the editor.

## Additional work beyond the prompt

None.

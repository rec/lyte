# Wearable Patch Library Plan

## Goal

Make `patches/wearable-breath.toml` an executable library of named MIDI light
patches for the 200-dot wearable. A selected patch must render through its
declared five-segment virtual device, receive MIDI input, and deliver the
result to the physical Twinkly string.

The implementation must remain generic: the wearable document is the first
library instance, not a special runtime path.

## Current Gaps

- `lyte/show.py` parses only animation, mixer, device, and run definitions.
  It does not parse a patch library or instantiate any graph.
- `Patch` knows note-on/off, CC 2, and pitch bend, but it has no declarative
  control-binding model.
- `BlendLightPatch` provides additive output and an overridable `blend()`
  method, but it has no data-defined blend policy or weights.
- `ConcatLightPatch` can render one child patch against a virtual device and
  return segment frames, but nothing loads named segments from TOML or sends
  those frames through output playback.
- The current TOML uses descriptive strings such as `"CC 2 maps ..."`. They
  are useful design notes but cannot be validated or executed.

## Target TOML Schema

Replace descriptive control strings with tables. Keep the existing named patch
tables, segment names, and layer names.

```toml
[wearable]
led_count = 200

[wearable.segments.left_leg]
start = 0
led_count = 32

[patches.breath_mix_walk_twinkle]
segments = ["left_leg", "right_leg", "left_arm", "right_arm", "chest"]
layers = ["random_walk", "region_twinkle"]

[patches.breath_mix_walk_twinkle.controls.note]
target = "palette.root_hue"
map = "note_hue"

[patches.breath_mix_walk_twinkle.controls.breath_speed]
source = { kind = "control_change", control = 2 }
target = "random_walk.speed"
map = { kind = "linear", input = [0, 127], output = [1.0, 80.0] }

[patches.breath_mix_walk_twinkle.controls.breath_mix]
source = { kind = "control_change", control = 2 }
target = "blend.weight.1"
map = { kind = "linear", input = [0, 127], output = [0.0, 1.0] }

[patches.pitch_turbo_chase.controls.pitch_speed]
source = { kind = "pitchwheel" }
target = "body_chase.speed"
map = { kind = "linear", input = [0, 8191], output = [1.0, 300.0] }
```

Use named targets rather than embedding Python expressions in TOML. The
runtime maps each allowed target name to a defined patch parameter or blend
weight. Negative pitch bend should retain the target's ordinary speed unless a
future patch explicitly opts into a lower-speed mapping.

## Models And Parsing

1. Add frozen Pydantic models in a new `lyte/patches.py` module:
   `PatchLibrary`, `WearableSpec`, `PatchSpec`, `LayerSpec`, `ControlSpec`,
   `ControlSourceSpec`, and `LinearMapSpec`.
2. Represent `WearableSpec.segments` with named `DeviceSegment` definitions.
   Validate non-negative starts, positive lengths, no overlap, and exact total
   coverage of `wearable.led_count`.
3. Add `load_patch_library(path)` using `tomllib`. Reject unknown fields,
   duplicate layer names, unknown segment names, unknown control targets, and
   invalid control ranges with source-qualified errors.
4. Keep patch-library parsing separate from `ShowFile` initially. Add a
   `patch_library` reference to a show only after standalone loading and
   playback work. This avoids changing the existing show-file merge rules
   while the schema is still being proven.

## Patch Construction

1. Create a registry that maps layer names such as `random_walk`,
   `body_chase`, `region_twinkle`, and `five_phase_rainbow` to concrete
   `LightPatch` factories. A factory receives only validated layer parameters.
2. Add a generic `SegmentLightPatch` that owns named `Animation` descriptions
   and states, renders each one through `SegmentAnimation`, and exposes the
   resulting 200-dot virtual frame as a `LightPatch`.
3. Build multi-layer patches with `BlendLightPatch`. Its default remains the
   current clipped additive blend.
4. Add a `WeightedBlendLightPatch` subclass. It stores mutable weights in its
   state and overrides `blend()` to use them. It is used only by patch specs
   that declare a blend control.
5. Build the complete named patch graph once per selected patch. Its immutable
   descriptions belong to the library; each note-on creates fresh mutable
   state as existing `Patch` semantics require.

## MIDI Controls

1. Generalize `Patch.receive()` dispatch into typed note, control-change, and
   pitch-wheel handlers without changing its note lifecycle.
2. Add a reusable control mapper that normalizes MIDI values, applies the
   validated linear map, and writes a declared mutable target.
3. Route one incoming message first to the outer patch's declared bindings,
   then to all child patches. This preserves the desired behavior where breath
   can affect both a blend weight and child animation speed, but only when the
   patch spec declares both bindings.
4. Implement note-to-colour as a fixed pitch-class hue mapping. The control
   binding chooses which layer palette or colour parameter receives it.
5. Implement pitch turbo as a one-sided mapping from positive pitch bend to
   the declared high-speed range. Keep its default value independent of breath.

## Playback And Output

1. Add a patch playback loop that renders the selected `LightPatch` at a
   requested FPS and uses the existing Twinkly frame output path.
2. For the wearable's one 200-dot string, render the virtual device directly.
   Use `ConcatLightPatch` only when a future physical configuration divides
   those five logical segments across devices or physical device ranges.
3. Add a Tyro patch command data class, for example `lyte patch`, with a
   library path, patch name, MIDI input selection, and existing output/retry
   configuration.
4. Ensure the existing shutdown path sends black when patch playback exits or
   is interrupted.

## Tests

1. Parse the current library and assert 32 unique patch names, the five
   expected segments, total 200 LEDs, and the required control-count totals.
2. Add invalid-library cases for gaps, overlaps, bad layer names, invalid MIDI
   controls, impossible maps, and unresolved targets.
3. Test a segment patch produces a `(200, 3)` contiguous float32 frame and
   sends each region's frame to its correct range.
4. Test a weighted blend at breath values `0`, `64`, and `127`, including a
   patch that also sends breath to a child speed target.
5. Test note colour mapping, positive pitch turbo, note-off state reset, and
   black output on playback shutdown with fake output transport.

## Physical Verification Order

1. Load and list the library without connecting to lights.
2. On the wearable, verify one five-segment locator patch and black shutdown.
3. Verify note-to-colour patches with one octave of notes.
4. Verify breath-speed patches at closed, medium, and sustained high breath.
5. Verify breath-mix patches at `0`, midpoint, and `127`, while confirming
   child speed controls still respond where declared.
6. Verify positive pitch turbo gradually, then at maximum bend, watching for
   dropped frames and network saturation.
7. Only then make random patch selection or show-file integration available.

## Additional work beyond the prompt

None.

# Wearable Patch Library Plan

## Goal

Make `patches/wearable-breath.toml` an executable library of named MIDI light
patches for the 200-dot wearable. A performer selects one named patch, plays a
note to activate it, and uses declared controls to affect it. The patch renders
through a five-region logical wearable and delivers the resulting frames to the
physical Twinkly string.

The implementation must remain generic: the wearable document is the first
library instance, not a special runtime path.

## Author Model

The following terms have distinct roles in a library file and runtime:

- **Library**: one TOML file containing a logical wearable, reusable layer
  definitions, and named patches.
- **Logical wearable**: a contiguous virtual 200-dot device divided into the
  five body regions used by a patch.
- **Physical map**: the translation from logical dot indexes to the actual
  order on the Twinkly string. It is explicitly provisional until a locator
  test measures it.
- **Layer**: a reusable effect definition with named parameters, such as
  `random_walk` and `speed`. A layer declares which parameters controls may
  change.
- **Patch**: a named composition of layers, regions, and optional control
  bindings. It is the item a performer selects.
- **Control binding**: a MIDI source, its mapping, and one allowed named
  parameter target. Every binding applies only while the patch has an active
  note.

A performer does not address a Python object, a physical LED index, or a
generic target string. They choose a patch name. A note-on creates that patch's
state and selects an entry from its declared note palette by pitch class. CC 2
and pitch bend affect only controls that the chosen patch explicitly declares.
Note-off clears patch state and outputs black.

## Logical And Physical Layout

The logical wearable is always 200 dots in this order:

| Region | Logical indexes | Dots |
| --- | ---: | ---: |
| `left_leg` | 0-31 | 32 |
| `right_leg` | 32-63 | 32 |
| `left_arm` | 64-107 | 44 |
| `right_arm` | 108-151 | 44 |
| `chest` | 152-199 | 48 |

The arm regions include the same-side torso run. This makes the five regions
useful for patch design even though the physical string is split differently.

The initial physical map is deliberately provisional. It derives from the
existing assumed two-branch layout, where each branch is arm (28 dots), leg
(32), side body (16), then chest (24):

| Logical region | Provisional physical source |
| --- | --- |
| `left_leg` | left branch, indexes 28-59 |
| `right_leg` | right branch, indexes 28-59 |
| `left_arm` | left branch, indexes 0-27 and 60-75 |
| `right_arm` | right branch, indexes 0-27 and 60-75 |
| `chest` | left branch, indexes 76-99; right branch, indexes 76-99 |

This table is a starting assumption, not a claim about the installed wearable.
The library must mark it as provisional. The first physical feature is a
locator patch that lights one logical region at a time. Its observed result
becomes the measured physical map used by all performance patches.

## Authoring Vocabulary

The library must define reusable layers before patches refer to them. Each
layer has an implementation name, its initial parameters, and a fixed list of
parameters that control bindings may change. A patch may use a layer only by
name, and may bind only a parameter that layer exposes.

The first vocabulary should be intentionally small:

| Layer kind | Required parameters | Controllable parameters |
| --- | --- | --- |
| `solid` | `color` | `color`, `gain` |
| `random_walk` | `color`, `speed` | `color`, `speed`, `gain` |
| `twinkle` | `color`, `rate` | `color`, `rate`, `gain` |
| `chase` | `color`, `speed` | `color`, `speed`, `gain` |
| `rainbow` | `speed` | `speed`, `gain` |

`layers` in the existing library must be converted into declared layer tables.
New layer kinds are Python implementations added deliberately; new instances
of an existing kind are ordinary TOML edits. This gives an author a bounded
catalogue instead of requiring them to infer free-form strings.

Every patch has `activation = "note"`. This is mandatory for the first format:
no patch accepts CC 2 or pitch bend without an active note. A later format may
introduce other activation policies only when there is a concrete need.

## Target TOML Schema

The following is a complete small patch. It is intended to be understandable
and valid without reading Python source.

```toml
[wearable]
led_count = 200
physical_map_status = "provisional"

[wearable.segments.left_leg]
start = 0
led_count = 32

[layers.leg_walk]
kind = "random_walk"
color = [1.0, 0.0, 0.0]
speed = 8.0
controls = ["color", "speed"]

[patches.note_walk]
activation = "note"
regions = ["left_leg", "right_leg"]
layers = ["leg_walk"]
note_palette = [
  [1.0, 0.0, 0.0], [1.0, 0.5, 0.0], [1.0, 1.0, 0.0],
  [0.0, 1.0, 0.0], [0.0, 1.0, 1.0], [0.0, 0.0, 1.0],
  [0.5, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 0.4, 0.7],
  [0.7, 0.2, 0.1], [0.4, 0.7, 0.1], [0.1, 0.4, 0.7],
]

[[patches.note_walk.bindings]]
source = "note"
target = "leg_walk.color"
map = "pitch_class_palette"

[[patches.note_walk.bindings]]
source = "breath"
target = "leg_walk.speed"
map = { kind = "linear", input = [0, 127], output = [1.0, 80.0] }
```

`note_palette` has twelve colors. MIDI pitch class, modulo twelve, selects its
color. The same palette entry applies for the life of the active note. A patch
may omit `note_palette` and its `note` binding when notes are only used for
activation.

The only first-version source names are `note`, `breath`, and `pitch_bend`.
`breath` means MIDI control change 2. `pitch_bend` uses only its positive half:
center and negative bend retain the target's base value, while maximum positive
bend maps to the stated upper value.

A mix is a named patch property, not an opaque numbered weight:

```toml
[patches.walk_and_twinkle]
activation = "note"
regions = ["left_leg", "right_leg", "left_arm", "right_arm", "chest"]
layers = ["body_walk", "body_twinkle"]
blend = "add"

[[patches.walk_and_twinkle.bindings]]
source = "breath"
target = "mix.body_twinkle"
map = { kind = "linear", input = [0, 127], output = [0.0, 1.0] }

[[patches.walk_and_twinkle.bindings]]
source = "breath"
target = "body_walk.speed"
map = { kind = "linear", input = [0, 127], output = [1.0, 40.0] }

[[patches.walk_and_twinkle.bindings]]
source = "pitch_bend"
target = "body_walk.speed"
map = { kind = "positive_linear", output = [40.0, 300.0] }
```

It is valid for one source to affect several explicitly declared targets. This
is how breath can change both a mix and a child effect's speed.

## Compiled Result

Loading is a fixed, inspectable transformation:

```text
TOML library
  -> validated library model
  -> selected patch specification
  -> named layer descriptions and control bindings
  -> logical 200-dot LightPatch
  -> physical-map output frames
  -> Twinkly frame output
```

The logical patch combines region frames and layer frames. The output mapper
then translates logical indexes to physical locations. This makes it possible
to test parsing, controls, and logical rendering without a Twinkly device, and
to replace only the physical map after the locator test.

## Implementation Order

1. Add frozen Pydantic models in `lyte/patches.py`: `PatchLibrary`,
   `WearableSpec`, `RegionSpec`, `PhysicalMapSpec`, `LayerSpec`, `PatchSpec`,
   `BindingSpec`, and `LinearMapSpec`. Reject unknown fields and give errors
   qualified by library path and table name.
2. Implement `load_patch_library(path)` using `tomllib`. Validate the five
   logical regions cover exactly 200 dots, each layer's parameters match its
   declared kind, each patch names known layers and regions, and each binding
   names an exposed target.
3. Add a non-hardware library inspection command that lists patches, their
   regions, layers, controls, and whether the physical map is provisional.
4. Implement the logical region renderer and physical-map output mapper. Keep
   it independent of Twinkly transport.
5. Add the locator patch and use it on the wearable to replace the provisional
   map with a measured one. Do not treat subsequent physical verification as
   meaningful until this is complete.
6. Add the five initial layer kinds and build a selected patch from declared
   layer instances. Use `BlendLightPatch` for the default clipped additive
   composition, with named mutable mix values only where bindings require them.
7. Generalize `Patch` message handling into note, breath, and pitch-bend
   handlers while preserving its note lifecycle. Apply all declared bindings
   only when state exists. Route a message to the outer patch's bindings and
   then its child patches.
8. Implement pitch-class palette selection, linear breath mappings, and the
   positive-only pitch turbo mapping. Do not introduce generic expressions or
   arbitrary Python paths in TOML.
9. Add patch playback through the existing Twinkly output and shutdown path.
   The command selects a library and patch name, MIDI input, FPS, and existing
   output configuration. It blacks out on normal exit and interruption.
10. Convert the 32 existing descriptive entries one category at a time. Each
    entry uses only the documented layer and binding vocabulary.
11. Keep patch libraries outside `ShowFile` until standalone loading,
    playback, and the measured map work. Add show-file references afterwards,
    without changing current show-file merge policy during this work.

## Tests

1. Parse the library and assert 32 unique patch names, the five expected
   logical regions, total 200 dots, and the existing control-count totals.
2. Test invalid libraries: gaps, overlaps, unknown layer kinds, unknown layer
   instances, invalid parameters, unknown regions, unresolved targets, and
   invalid ranges.
3. Test the inspection output identifies the provisional map.
4. Test the locator and physical-map mapper send each logical region to the
   correct provisional physical indexes.
5. Test each initial layer renders a contiguous `(200, 3)` `float32` logical
   frame through its declared regions.
6. Test note palette selection, note-off state reset, note-gated breath and
   pitch behavior, a combined breath speed and mix binding, and positive pitch
   turbo.
7. Test black output on playback shutdown with a fake output transport.

## Physical Verification Order

1. Load and inspect the library without connecting to lights.
2. Run the locator patch, record the actual illuminated dot ranges, and commit
   the measured physical map.
3. Verify black shutdown.
4. Verify note-palette patches across one octave.
5. Verify breath-speed and breath-mix patches at closed, midpoint, and high
   breath while holding an active note.
6. Verify pitch turbo from center to maximum positive bend while holding an
   active note, watching for dropped frames and network saturation.
7. Only then allow random patch selection or show-file integration.

## Additional work beyond the prompt

None.

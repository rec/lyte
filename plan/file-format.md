# Animation File Format Plan

Lyte should support a TOML-style file format for named animation graphs. The
format should represent either one animation or a collection of animations,
including references between animations, animation composition, device routing,
and mixing multiple animations into one device output.

The file format should be declarative. Concrete behavior should live in Python
classes or functions and be referenced by import path. Runtime loading should
resolve those paths, validate the configured models, and build the animation or
patch graph.

## Current Implementation

`lyte show` is currently an offline preflight command. It loads and merges TOML
files, validates references, constructs trusted local Python animation graphs,
and allocates a separate `Device` and mutable `State` for each `[run]` target.
It does not render frames, open a Twinkly connection, send output, or perform
blackout cleanup.

The only supported device kind is `twinkly`. A current run target requires its
device to declare `led_count`; the current preflight uses no other device or
run-target settings. In particular, `host`, `brightness`, and `channel_map`
are future track configuration, not working Show File options.

The remaining sections describe the intended format and must not be read as a
claim that a show runner, mixer implementations, or non-Twinkly output exists.

## Goals

- Represent one named animation or a collection of named animations.
- Let animations reference other animations by name.
- Let animations combine other animations through explicit combiner nodes.
- Let one animation send to multiple devices.
- Let multiple animations send to the same device through a `Mixer`.
- Let implementation classes and functions be referenced by Python import path.
- Keep the first format small enough to hand-write.
- Keep device protocol details out of animation definitions where practical.

## Non-Goals

- Do not invent a graphical show editor format.
- Do not serialize live mutable playback state as part of the first pass.
- Do not add compatibility for old script arguments.
- Do not make TOML the only possible future format if another representation is
  later useful.
- Do not implement multi-protocol device support as part of the file parser
  unless the current command being added needs it.

## Core Concepts

The file has four main sections:

- `run`: a device-to-source map selecting what should actually play.
- `animations`: named renderable definitions.
- `mixers`: named combiners for multiple animations targeting the same device.
- `devices`: named physical or virtual output targets.

An animation name is a file-local identifier. It is how other animations,
mixers, and run targets refer to that animation.

An implementation path is a Python dotted path to a class or factory function,
for example:

```toml
impl = "lyte.animations.bibliopixel.rainbow.Rainbow"
```

If the path resolves to a class, Lyte should instantiate it from the TOML
parameters. If the path resolves to a function, Lyte should call it with the
same parameters and expect it to return a compatible animation or patch object.

## Single Animation Example

A minimal playable file can contain one animation, one device, and a `run`
section that maps the device to the animation:

```toml
[run]
tree = "rainbow"

[animations.rainbow]
impl = "lyte.animations.bibliopixel.rainbow.Rainbow"

[devices.tree]
kind = "twinkly"
led_count = 250
```

Today this validates the graph and creates device-local playback state for
`tree`. A later Twinkly track will render and stream the result.

## Collection Example

A file can contain multiple named animations:

```toml
[animations.base]
impl = "lyte.animations.bibliopixel.color_fill.ColorFill"
color = [10, 20, 255]

[animations.sparkle]
impl = "lyte.animations.bibliopixel.twinkle.Twinkle"
density = 0.1

[devices.tree]
kind = "twinkly"
led_count = 250

[devices.window]
kind = "twinkly"
led_count = 250

[run]
tree = "base"

[run.window]
source = "window_mix"

[mixers.window_mix]
impl = "lyte.composition.AdditiveMixer"
sources = ["base", "sparkle"]
```

The same animation can run on multiple devices. Each run target should create
device-local playback state, so two devices using the same immutable animation
description do not accidentally share mutable state.

## Animation References

Animations can refer to other animations by name. A reference is always explicit
and should use a list field whose values are animation names:

```toml
[animations.fade]
impl = "lyte.composition.Crossfade"
sources = ["blue", "sparkle"]
duration = 4.0

[animations.blue]
impl = "lyte.animations.bibliopixel.color_fill.ColorFill"
color = [0, 0, 255]

[animations.sparkle]
impl = "lyte.animations.bibliopixel.twinkle.Twinkle"
```

The loader should resolve references after parsing all named animations. Missing
names should be a validation error. Reference cycles should be rejected unless a
future recursive or feedback animation explicitly supports them.

## Combining Animations

Composition should be represented by ordinary named animation nodes. A combiner
is just an implementation whose parameters include references to other named
animations:

```toml
[animations.look]
impl = "lyte.composition.Add"
sources = ["wash", "sparkle", "pulse"]
clip = true
```

The important rule is that composition happens before `run` maps a source to a
device. This keeps animation graphs reusable across devices.

Initial combiners should probably include:

- `Add`: sum frames and optionally clip.
- `Multiply`: multiply frames for masks and gain.
- `Crossfade`: blend two sources by time or control signal.
- `Sequence`: play sources one after another.

These combiners should be normal Python implementations. The file format only
needs a consistent way to name sources and pass parameters.

## Devices

Devices should describe output targets, not animations:

```toml
[devices.tree]
kind = "twinkly"
host = "192.168.1.23"
led_count = 250

[devices.arch]
kind = "twinkly"
host = "192.168.1.24"
```

For now, `kind = "twinkly"` is enough. Later kinds can include `dmx`, `artnet`,
`osc`, or virtual preview devices.

Device sections should map to device-specific Pydantic config models. Generic
code should not need to know every field for every protocol; it should dispatch
by `kind`.

## Run Section

The `run` section selects which of the many possible animations or mixers in
the file should actually play. A file can define a library of reusable looks
without running all of them.

The first format should make `run` a dictionary keyed by device name:

```toml
[run]
tree = "look"
arch = "look"
```

The `source` can name an animation or a mixer. Run-target-local
parameters such as brightness and channel mapping are future track work and are
not accepted as active configuration yet. Later, `run` can grow show-level
options by reserving top-level keys if that becomes necessary. Those options
should not be inferred from all definitions in the file.

A file with no `run` section is a library file. It can be imported or combined
with another show file, but it should not be playable by itself unless the CLI
explicitly names a device and source to run. Run-target transforms should be
output-boundary adjustments, not changes to the source animation object.

## Mixers

When multiple animations send to the same device, the device should receive one
final frame from a `Mixer`.

```toml
[mixers.tree_mix]
impl = "lyte.composition.AdditiveMixer"
sources = ["background", "sparkle", "midi_solo"]
clip = true

[run]
tree = "tree_mix"
```

A `Mixer` differs from a normal animation combiner mainly by role:

- It is the last composition step before a device output.
- It owns policy for combining independent sources for one device.
- It is where source priorities, clipping, blend modes, solo/mute, and master
  gain should eventually live.

The first implementation can treat mixers and animation combiners similarly in
code, but the file format should keep the concept separate because users will
think of device output mixes differently from reusable animation definitions.

If multiple animations should send to the same device, the run target should
name an explicit mixer. Silent implicit mixing can hide mistakes in show files.

## Combining Show Files

A `ShowFile` should have an explicit policy for combining two or more files.
This is needed so a base library file, a device file, and a show-specific file
can be loaded together without ambiguous overrides.

The first policy should be strict merge by namespace:

- `animations`, `mixers`, and `devices` are merged by name.
- Duplicate names in the same namespace are errors by default.
- `run` is not merged implicitly; the last loaded playable file must provide the
  run section, or the CLI must name the run entry point.
- Library files should omit `run`.
- A later explicit override syntax can be added if real use needs it.

This keeps composition predictable. For example, a library can define
`animations.sparkle`, a device file can define `devices.tree`, and the show file
can define `[run]`. If two files both define `animations.sparkle`, the loader
should fail until the user renames one or uses an explicit override feature.

If more than one loaded file contains `[run]`, the first pass should fail unless
the CLI explicitly chooses one file as the playable entry point. That avoids
accidentally running entries from a library or device inventory file.

## Runtime Loading

The loader should work in stages:

1. Parse each TOML file into raw dictionaries.
2. Validate top-level section shapes for each file.
3. Strictly merge all input files into one `ShowFile`.
4. Validate `run` device names and sources against the merged namespaces.
5. Build device configs from `devices`.
6. Resolve implementation paths for animations and mixers.
7. Validate constructor parameters using the target Pydantic models where
   possible.
8. Resolve named animation references.
9. Build an immutable show graph.
10. Create per-device mutable playback state at run time.

Implementation path loading should be narrow:

- import the module
- read the final attribute
- verify it is callable or is a compatible class
- instantiate or call with validated parameters

Errors should include the animation, mixer, device, or run target that failed.

## Suggested Data Model

The in-memory model can start with small Pydantic models:

```text
ShowFile
  run: dict[str, RunTargetSpec] | None
  animations: dict[str, AnimationSpec]
  mixers: dict[str, MixerSpec]
  devices: dict[str, DeviceSpec]

RunTargetSpec
  source: str
  params: dict[str, object]

AnimationSpec
  impl: str
  params: dict[str, object]

MixerSpec
  impl: str
  sources: list[str]
  params: dict[str, object]

DeviceSpec
  kind: str
  params: dict[str, object]

```

In TOML, unknown keys in a section should become `params` after reserved keys
such as `impl`, `kind`, `source`, and `sources` are removed.

## File Validation Rules

- Names must be unique within each namespace.
- `run` keys must name devices.
- Run target `source` must name either an animation or a mixer.
- Mixer `sources` must name animations or mixers.
- Animation reference fields must name animations or mixers according to the
  target implementation's declared schema.
- Cycles must be rejected.
- Multiple sources targeting one device require an explicit mixer in the first
  pass.
- Duplicate names while combining files are errors unless a future explicit
  override syntax says otherwise.
- A file with exactly one animation and no `run` section can be loaded as a
  reusable animation library, but it cannot be played until mapped in `run` or
  explicitly selected by the CLI.

## Implementation Order

1. Add `plan/file-format.md`.
2. Add parser models for raw TOML specs, including `run` targets.
3. Add strict `ShowFile` merge validation for multiple input files.
4. Add Python path resolution and validation helpers.
5. Add graph validation for names, selected run targets, missing references, and
   cycles.
6. Add construction of animation and mixer objects.
7. Add per-device state creation for the selected run targets.
8. Add a CLI command to validate a file without playing it.
9. Add a CLI command or option to play one or more files.
10. Add mixer implementations after the basic loader exists.
11. Add examples for one animation, a reusable library, one source mapped to
    multiple devices, multiple files loaded together, and multiple sources mixed
    to one device.

## Additional Work Beyond the Prompt

None.

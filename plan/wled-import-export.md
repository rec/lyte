# WLED Import and Export

## Goal

Let Lyte exchange useful lighting material with WLED without claiming that two
unrelated effect engines are automatically interchangeable.

The finished system has four explicit capabilities:

1. Import a portable snapshot of a WLED controller's native effects, palettes,
   effect metadata, and saved presets.
2. Keep imported WLED presets as WLED-native data that can be inspected,
   named, and exported again without loss.
3. Translate a deliberately supported subset of WLED presets into Ufor scores
   or Lyte parameterized animations.
4. Send any Lyte-rendered RGB animation to a WLED controller in realtime.

This is not a generic compiler from WLED firmware effects to Ufor animations.
WLED's effect implementations, segment behavior, palettes, random sources,
audio features, and controller timing are different from Lyte's. Every actual
effect translation must be declared and tested as an individual mapping.

## Terms

- A **WLED snapshot** is a portable record of one controller's advertised
  capability and saved content. It is input material, not a Lyte animation
  library.
- A **WLED preset** is native WLED state: one or more segments, effect IDs,
  colors, palettes, speed, intensity, transitions, and optional commands.
- A **translation** maps one documented WLED effect and its supported preset
  settings to one authored Ufor selector and its public parameters.
- **WLED realtime output** streams Lyte RGB frames to WLED through DDP. It
  does not install or synthesize a native WLED effect.

## Input and Output Boundaries

### Snapshot Import

The first importer is file-based. It reads a downloaded `presets.json` backup
and a separately captured WLED metadata document containing the `/json/eff`,
`/json/fxdata`, `/json/pal`, and `/json/info` responses. This avoids requiring
an address in a Lyte document and makes source content reviewable and
repeatable.

The importer writes one canonical Lyte WLED snapshot document. Preserve the
original JSON objects under `raw`, excluding network identity fields, alongside
parsed fields. The parsed model contains:

- WLED firmware version, controller name, LED count, and reported capabilities;
- effect names and the per-effect metadata needed to interpret sliders;
- palette names and custom palette data when present;
- named presets, preset IDs, segment state, playlist state, and commands;
- snapshot timestamp and source-file hashes.

MAC addresses, IP addresses, Wi-Fi details, tokens, and any other network
identity are excluded from the snapshot. They are neither imported nor emitted.

Reject malformed source files with source paths and exact field diagnostics.
Retain unknown WLED fields in `raw`; WLED evolves more quickly than Lyte's
typed model.

### Native WLED Preset Export

Exporting a WLED snapshot or an unmodified WLED-native preset writes WLED JSON
that can be restored to WLED. This is a lossless data export, not animation
translation.

Lyte-generated WLED presets are allowed only for a supported declarative
subset: static color, brightness, transition, named palette, simple segment
range, and a mapped native effect. The exporter must reject unsupported Ufor
operations rather than silently flattening them into unrelated WLED settings.

### Ufor Translation

Translations live in a Lyte-owned mapping table, not in the imported snapshot.
Each entry includes:

- stable WLED effect name and optional known firmware range;
- accepted WLED preset fields and ranges;
- Ufor selector;
- explicit conversion functions for colors, speed, intensity, palette, and
  segment size;
- a statement of behavioral differences;
- source provenance and the test fixture that demonstrates the mapping.

Start with one-dimensional effects whose semantics are already close to Lyte:
solid, breathe, chase, chase rainbow, candle, color wipe, comet, rainbow,
scan, and twinkle. Do not translate audio-reactive, particle-system, image,
playlist, usermod, or two-dimensional effects in the first release.

An imported preset with a translation produces a separate generated Ufor score
or a selector plus parameter preset. An unsupported preset remains available
as a native WLED preset with an explicit `not_translated` reason.

### WLED Realtime Output

Add a WLED output driver alongside Twinkly output. It owns:

- authenticated-free WLED DDP frame delivery to the controller's realtime
  input;
- DDP packet chunking, RGB byte order, offset, frame boundaries, and delivery
  errors;
- resampling from the authored frame count to the controller's discovered LED
  count;
- bounded network recovery and per-output Reccy status.

WLED accepts DDP on port 4048. Lyte must use DDP rather than an ad hoc WLED
JSON per-pixel update path. JSON remains for capability and preset operations;
DDP is the high-rate pixel transport.

Do not put a WLED IP address, MAC address, or LED count in installation files.
The later live-device workflow discovers WLED controllers, reads `/json/info`,
and assigns semantic output names through non-secret observed fields such as
the controller name and reported capabilities. An offline snapshot workflow
does not need device discovery.

## Command Design

```sh
lyte wled import snapshot-input/ --output wled-snapshot.json
lyte wled export wled-snapshot.json --output presets.json
lyte wled translate wled-snapshot.json --output ufor-scores/
lyte wled list wled-snapshot.json
```

`import` accepts a directory so the source backup files remain together.
`list` reports native presets, their WLED effect and palette, and whether a
translation exists. `translate` never overwrites authored Ufor score files; it
writes into a generated directory with a manifest linking every result to its
source preset.

The realtime driver is selected through the normal installation output model,
not through `lyte wled export`. Export creates files; output playback drives a
connected controller.

## Data Ownership

- WLED source files and snapshots are immutable inputs. Do not rewrite them.
- Lyte owns the canonical snapshot, translation map, generated-score manifest,
  and export document.
- Ufor owns translated score structure, layout, composition, and parameters.
- The WLED driver owns network transport and discovered output facts.

Do not copy WLED effect source into Lyte as part of this work. Implementations
inspired by WLED must be independently designed, cite their effect provenance,
and receive their own regression fixtures. Any direct reuse of WLED code
requires a separate license review under WLED's EUPL-1.2 terms.

## Validation

1. A snapshot has all required source documents and matching effect and palette
   references.
2. Every preset effect ID resolves against that snapshot's effect list, unless
   WLED marked the ID unavailable.
3. Every translated preset names a registered translation and satisfies its
   declared input range.
4. Generated Ufor scores pass normal Ufor library validation and Lyte renderer
   preparation.
5. A native preset export round-trips to the same parsed preset data, excluding
   source formatting and explicitly ignored WLED metadata.
6. Realtime output accepts any positive discovered LED count and resamples
   frames instead of rejecting a mismatch.
7. Live device discovery does not persist network identities in installation
   documents or snapshots.

## Status and Failures

The realtime WLED driver reports through Reccy:

- discovery and assignment state;
- controller name and detected LED count;
- active animation and frame-send count;
- packet and recovery failures;
- current source-to-device scaling warning.

A preset import or translation failure identifies the preset ID and name,
effect, field, and source path. One unsupported preset never blocks importing
the rest of a snapshot. A realtime WLED output failure is isolated from other
physical outputs.

## Implementation Steps

1. Add fixture snapshots from at least two WLED versions, with presets using
   multiple segments, palettes, transitions, unavailable effect IDs, and an
   unknown forward-compatible field.
2. Create typed WLED snapshot and native preset models plus a lossless raw-data
   envelope. Implement file import, validation, and deterministic export.
3. Add the `lyte wled import`, `list`, and `export` Tyro commands with source
   paths, output paths, and concise diagnostics.
4. Create the translation registry and generated-score manifest. Implement the
   initial one-dimensional mappings one at a time, with fixed frame fixtures
   for the mapped Lyte behavior.
5. Add the DDP packet encoder and an output driver using the existing retry,
   scaling, logging, and Reccy status patterns.
6. Add WLED capability discovery and selector-based assignment only after the
   offline snapshot and DDP driver are working. Keep all discovered network
   identity transient.
7. Extend the installation model so a bound animation can target WLED outputs
   without duplicating the Twinkly binding language.
8. Perform hardware validation with one WLED controller: preset restore,
   DDP frame ordering, 250/500 count rescaling, reconnect recovery, and
   coexistence with a Twinkly string.

## Tests

- Snapshot import/export round-trip fixtures.
- Unknown-field retention and malformed-file diagnostics.
- Preset effect and palette reference validation.
- One fixture per supported WLED-to-Ufor translation, including its declared
  approximation differences.
- Rejection of unsupported effects without loss of native preset data.
- Exact DDP packet bytes, chunk boundaries, offsets, and RGB order.
- Frame scaling for mismatched authored and WLED LED counts.
- Realtime output failures and recovery status without affecting a healthy
  Twinkly output.
- Assurance that snapshot and installation serialization never contain a host,
  MAC address, or token.

## Non-Goals

- Automatic conversion of arbitrary WLED firmware effects.
- Importing WLED source code or compiling WLED effects inside Lyte.
- Translating audio-reactive, 2D, particle, image, playlist, or usermod effects
  in the initial release.
- Replacing WLED's preset editor or controller firmware.
- Treating exported WLED presets as portable Ufor scores.

## Additional work beyond the prompt

None.

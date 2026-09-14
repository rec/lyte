# Animation Editor Next Steps

## Save-As

Investigate the Ufor API for a lossless TOML representation. Add an explicit
save-as workflow only when it can write a new human-readable Ufor score without
discarding unknown source fields. The server must validate and prepare the
candidate before reporting success, and it must never overwrite a source score
by default.

If lossless score serialization is unavailable, begin by saving a small,
separate parameter-preset document with an explicit Ufor selector. Built-in
reactive effects remain preview-only until they have a declared Ufor score
representation.

## Composition Inspector and Editing

Add a read-only composition tree for the selected output. It should show Ufor
effects, fills, sources, placements, mixes, reverses, gains, crossfades, cues,
and component maps. Selecting a node should show its declared fields and
diagnostics.

After score save round trips are reliable, add structure editing through
score-aware templates. Every edit must pass Ufor validation, retain the last
valid preview on failure, and show the diagnostic beside the responsible field
or node. Do not introduce a separate node-graph format.

## Cue Timeline

Represent existing Ufor cues and crossfades on a timeline after composition
editing works. Preserve exact rational positions and durations while offering
seconds or beats only where the score timebase makes them unambiguous. The
timeline is a view of Ufor operations, not a universal keyframe system.

## Validation

Add save round-trip fixtures, including unknown-field retention and rejected
edits that leave the previous score usable. Test composition diagnostics and
cue timing. Manually verify a ring or other two-dimensional layout in `lyte
author`, including parameter edits, transport controls, pause, and seeking.

## Boundaries

The editor remains loopback-only and hardware-free. Twinkly, WLED, DMX, and
Art-Net output stay separate deliberate playback actions. Wiring remains a
physical output concern and is never applied to the editor visualizer.

## Additional work beyond the prompt

None.

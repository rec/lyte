# Floating-Point Color Plan

Lyte should move animation and color computation from `uint8` RGB frames to
`float32` RGB frames. Integer byte frames should become a final output encoding
step owned by preview, Twinkly, DMX, or other protocol drivers.

The reason to do this now is that 8-bit RGB is convenient but too specific. It
matches Twinkly and DMX byte output, but it is a poor working model for fades,
gain, gamma correction, empirical device remapping, color correction, and future
protocols with different output depth.

## Goals

- Use `float32` for all internal RGB frame computation.
- Use the normalized channel range `0.0..1.0` for internal RGB values.
- Convert to protocol-specific integers only at output boundaries.
- Preserve current animation behavior as closely as practical during the port.
- Port the BiblioPixel-derived animations rather than keeping a byte-only
  compatibility layer.
- Make gamma correction, Twinkly empirical LUT mapping, and temporal dithering
  operate before final byte encoding.
- Keep Twinkly realtime output as `uint8` bytes on the wire.

## Non-Goals

- Do not implement Twinkly brightness compensation as part of the first float
  migration.
- Do not implement white balance or color calibration in the first pass.
- Do not keep two public animation APIs.
- Do not add adapter layers for old `uint8` animation output unless a temporary
  internal step is needed inside one commit.
- Do not change DMX or multi-protocol architecture in this migration.

## Target Frame Model

Internal pixel frames should have this contract:

```text
shape: (device.led_count, 3)
dtype: np.float32
channels: red, green, blue
range: 0.0..1.0
layout: C-contiguous
```

The existing `Animation.render(device, state)` flow should remain, but its
return type should change from `NDArray[np.uint8]` to `NDArray[np.float32]`.

The validation helper should become something like:

```python
def validate_frame(device: Device, frame: NDArray[np.float32]) -> NDArray[np.float32]:
    ...
```

It should validate dtype, shape, contiguity, and finite values. It should not
silently clip out-of-range values. Out-of-range colors should be a rendering
bug, not a hidden output decision.

## Type Names

Add explicit names for the two different concepts:

- `RGB`: legacy or user-facing 8-bit color tuple, `tuple[int, int, int]`.
- `FloatRGB`: internal normalized color tuple, `tuple[float, float, float]`.
- `FloatFrame`: `NDArray[np.float32]`, shape `(led_count, 3)`.
- `ByteFrame`: `NDArray[np.uint8]`, shape `(led_count, 3)`.

Type aliases should be used only where they make code clearer. If the alias
syntax becomes noisy, keep annotations explicit and make helper names carry the
meaning.

## Boundary Conversion

Add explicit helpers for output encoding:

```text
float_rgb_frame(...)
solid_float_frame(...)
byte_frame_from_float(frame)
float_color_from_rgb(color)
rgb_from_float_color(color)
```

The normal byte conversion should:

1. validate `float32` frame shape and finite values
2. clip to `0.0..1.0` only at the output boundary
3. multiply by 255
4. round
5. cast to `np.uint8`
6. return a C-contiguous byte frame

Clipping belongs here because external control signals, gain, or crossfades may
slightly overshoot. Animation render methods should still try to stay in range.

Twinkly realtime sending should receive byte frames exactly as it does today,
but the runner should convert float frames immediately before sending.

## Animation API Changes

Change the core `Animation` contract:

```text
render(...) -> FloatFrame
```

The runner owns conversion:

```text
float frame = animation.render(device, state)
output frame = encode_for_twinkly(float frame)
send output frame
```

Preview should also render from float frames and convert to CSS or encoded
preview payload values at the preview boundary.

The test FPS utilities and black-floor command are special cases. They are
hardware-output probes and may continue constructing byte frames directly where
they are explicitly testing Twinkly byte input values.

## Legacy BiblioPixel Port

BiblioPixel-derived animations currently use 8-bit RGB tuples and often depend
on integer arithmetic. They should be ported directly to normalized floats.

Keep constructor arguments as 8-bit RGB tuples for now, because they are concise
for command-line examples and existing defaults:

```text
ColorFill(color=(255, 0, 0))
```

Inside render code, convert palette values to normalized floats once per frame
or through helpers. Later, if useful, add explicit float color constructors or
validators. Do not make that part of the first migration unless it is necessary
to avoid confusing code.

Porting rules:

- `np.zeros(..., dtype=np.uint8)` becomes `np.zeros(..., dtype=np.float32)`.
- `np.empty(..., dtype=np.uint8)` becomes `np.empty(..., dtype=np.float32)`.
- Assignment of `RGB` byte tuples must pass through `float_color_from_rgb()`.
- Integer brightness levels `0..255` become scalar brightness `0.0..1.0`.
- `scale_color()` should return `FloatRGB` or be replaced by a float helper.
- `blend_color()` should blend float values without widening to `uint16`.
- `wheel_color()` can continue producing byte tuples temporarily, but a
  normalized `wheel_float_color()` is cleaner.
- State buffers such as `frame_buffer` in wipe/rainbow/ping-pong animations
  should become `float32`.

Behavior should be tested at byte-output equivalence where practical:

```text
old uint8 render
new float render -> byte_frame_from_float
same or intentionally near-same byte frame
```

If exact equivalence is impossible because rounding points move, preserve the
visible behavior and update tests deliberately.

## Hamiltonian And Random Walk

Hamiltonian and random walk already have float color concepts internally. They
should be easier to port:

- keep interpolation in float
- change `frame_array()` to return `float32` normalized frames
- remove final per-channel `round()` from animation render paths
- let output encoding do the final byte quantization

These modules should probably be ported before the BiblioPixel set, because
they prove the new float frame contract with less churn.

## Runner And Networking

The Twinkly network layer should remain byte-oriented:

- packet construction expects `uint8`
- UDP payloads are bytes
- protocol validation remains byte-frame validation

The runtime or runner should become the boundary:

```text
Animation.render() -> float32 frame
validate float frame
encode Twinkly byte frame
validate byte frame
send byte frame
```

This keeps device-specific compensation in one place. Later Twinkly output can
be:

```text
float frame
-> gain / gamma / empirical LUT / spatial dither
-> uint8 byte frame
-> UDP packet
```

DMX output can use a different encoder without requiring animation code to know
about DMX channel depth or fixture profiles.

## Preview

Preview rendering should use the same float animation output as live playback.
The HTML preview can still store or display 8-bit color values after converting
float frames at the preview boundary.

This gives preview the same animation math as hardware output while keeping the
generated HTML compact and simple.

## Temporal Dithering

The current temporal dithering prototype operates on byte levels. It should not
be generalized in that form.

After the float migration:

- animation produces ideal `float32` brightness
- output mapping chooses neighboring device-visible levels
- temporal or spatial dithering chooses which pixels receive each level
- the final result becomes a byte frame

This means dithering becomes part of output encoding, not part of animation
rendering.

The existing `test2` command can be left as a hardware experiment during the
migration, but reusable dithering should be written against float frames and
device output maps.

## Test Strategy

Tests should move in stages:

1. Add float frame validation tests.
2. Add byte encoding tests for clipping, rounding, dtype, and shape.
3. Port one simple animation and assert encoded byte output matches current
   behavior.
4. Port Hamiltonian and RandomWalk.
5. Port BiblioPixel animations one file at a time.
6. Update preview tests to assert equivalent encoded output.
7. Keep network packet tests byte-based.

Avoid testing implementation details like private helper order. Test visible
frame output and validation failures.

## Migration Sequence

1. Add float frame helpers and byte encoder while keeping current animation
   render type unchanged.
2. Change `Animation.render()` and `validate_frame()` to the float contract.
3. Update the runner to encode float frames before Twinkly send.
4. Port Hamiltonian.
5. Port RandomWalk.
6. Port shared color helpers in `lyte/animations/colors.py`.
7. Port BiblioPixel animations one module at a time.
8. Update preview rendering to consume float frames.
9. Update `lyte test2` or replace its byte-level dither with float-output
   mapping once the migration is stable.
10. Search for remaining `NDArray[np.uint8]` animation render annotations,
    `dtype=np.uint8` frame construction, and direct RGB byte assignment.
11. Remove any temporary conversion helpers used only during migration.

Each commit should leave tests passing. If the port is too large for one safe
change, commit the helper/boundary work first, then commit animation families in
small batches.

## Open Questions

- Should animation constructor colors remain byte RGB tuples permanently, or
  should Lyte eventually expose user-facing float color constructors?
- Should out-of-range float frames fail at animation validation or only clip at
  output encoding? The plan recommends validation failure for render outputs and
  clipping only inside explicit output encoders.
- Should Twinkly empirical LUT compensation be configured per device, per model,
  or as a command-line option first?

## Additional Work Beyond the Prompt

None.

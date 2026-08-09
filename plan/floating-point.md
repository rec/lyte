# Floating-Point LightChannel Plan

Lyte should move animation and color computation from `uint8` RGB frames to
`float32` light-channel frames. Integer byte frames should become a final output
encoding step owned by preview, Twinkly, or other protocol drivers.

The reason to do this now is that 8-bit RGB is convenient but too specific. It
matches Twinkly byte output, but it is a poor working model for fades, gain,
gamma correction, empirical device remapping, color correction, and future
outputs with different output depth or different light-channel layouts.

## Goals

- Use `float32` for all internal light-channel computation.
- Use the normalized light-channel range `0.0..1.0` for internal values.
- Convert to protocol-specific integers only at output boundaries.
- Do not hard-code three color light channels into the core frame model.
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
- Do not change DMX or multi-protocol architecture in this migration. DMX is
  deliberately put aside until the Twinkly float migration is stable.

## Deferred Color Conversion

RGB-to-other-light-channel conversion is explicitly deferred. Lyte does not yet
have a specified BiblioPixel-derived color model for RGBW, warm/cool white, or
other channel layouts, so it must not infer one from generic channel names.

Until that model is specified, current runtime code remains RGB-only and no
RGBW extraction, RGB-to-luminance, white-balance, or generic device-profile
conversion policy should be added. References below to future channel layouts
are planning constraints, not an approved encoder design.


## Target Frame Model

Internal pixel frames should eventually have this contract:

```text
shape: (device.light_count, device.light_channel_count)
dtype: np.float32
light channels: device/profile-defined
range: 0.0..1.0
layout: C-contiguous
```

`device.light_count` is the number of independently addressed lights. For the
current Twinkly work this is the same thing as `led_count`.

`device.light_channel_count` is the number of controlled light components per
light. It is `3` for RGB, but it may be `1` for single-color strands, `2` for
warm/cool white, `4` for RGBW, or more for layouts with amber, lime,
ultraviolet, or other emitters.

Light-channel identity belongs to the device or output profile. The core frame
model should not assume that light channels 0, 1, and 2 are always red, green,
and blue. RGB-only animations may still declare that they produce RGB frames,
and RGB outputs remain the first migration target, but the generic frame storage
should allow any light-channel count.

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

Add explicit names for the different concepts:

- `RGB`: legacy or user-facing 8-bit color tuple, `tuple[int, int, int]`.
- `FloatRGB`: normalized RGB color tuple, `tuple[float, float, float]`.
- `FloatLightFrame`: `NDArray[np.float32]`, shape
  `(light_count, light_channel_count)`.
- `FloatRGBFrame`: `NDArray[np.float32]`, shape `(light_count, 3)`.
- `ByteLightFrame`: `NDArray[np.uint8]`, shape
  `(light_count, light_channel_count)`.
- `ByteRGBFrame`: `NDArray[np.uint8]`, shape `(light_count, 3)`.
- `LightChannel`: semantic light component such as `red`, `green`, `blue`,
  `white`, `warm_white`, `cool_white`, `amber`, `lime`, or `ultraviolet`.
- `LightChannelLayout`: immutable light-channel labels and output meaning for a
  device.

Type aliases should be used only where they make code clearer. If the alias
syntax becomes noisy, keep annotations explicit and make helper names carry the
meaning.

The first implementation can use `FloatRGBFrame` for existing animations, but it
should not name that type as the universal frame model.

## Boundary Conversion

Add explicit helpers for output encoding:

```text
float_rgb_frame(...)
solid_float_light_frame(...)
byte_light_frame_from_float(frame)
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

RGBW and non-RGB output conversion is deferred until the intended
BiblioPixel-derived color model is specified. This plan intentionally does not
choose an extraction, luminance, white-balance, or profile conversion policy.

## Animation API Changes

Change the core `Animation` contract:

```text
render(...) -> FloatLightFrame
```

The runner owns conversion:

```text
float light frame = animation.render(device, state)
output frame = encode_for_device(float light frame)
send output frame
```

Preview should also render from float frames and convert to CSS or encoded
preview payload values at the preview boundary.

Existing animations are RGB animations. During the first migration, their
rendered shape can remain `(led_count, 3)` as a specialized `FloatRGBFrame`.
The important architectural change is that the output layer, not the animation
base class, should be the place where RGB is mapped to a concrete device
light-channel layout.

The test FPS utilities and black-floor command are special cases. They are
hardware-output probes and may continue constructing byte frames directly where
they are explicitly testing Twinkly byte input values.

## Legacy BiblioPixel Port

BiblioPixel-derived animations currently use 8-bit RGB tuples and often depend
on integer arithmetic. They are RGB animations, and they should be ported
directly to normalized RGB floats.

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
new float render -> byte_light_frame_from_float
same or intentionally near-same byte frame
```

If exact equivalence is impossible because rounding points move, preserve the
visible behavior and update tests deliberately.

## Hamiltonian And Random Walk

Hamiltonian and random walk already have float color concepts internally. They
should be easier to port:

- keep interpolation in float
- change `frame_array()` to return `float32` normalized frames
- remove final per-light-channel `round()` from animation render paths
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
Animation.render() -> float32 light frame
validate float light frame
map to device light-channel layout
encode device byte frame
validate byte frame
send byte frame
```

This keeps device-specific compensation in one place. Later Twinkly output can
be:

```text
float light frame
-> RGB-to-device light-channel mapping if needed
-> gain / gamma / empirical LUT / spatial dither
-> uint8 byte frame
-> UDP packet
```

DMX is intentionally out of scope for this migration. When DMX work resumes, it
should use its own encoder boundary rather than forcing animation code to know
about DMX protocol slots or fixture profiles.

## Preview

Preview rendering should use the same float animation output as live playback.
The HTML preview can still store or display 8-bit color values after converting
float frames at the preview boundary.

This gives preview the same animation math as hardware output while keeping the
generated HTML compact and simple.

The preview renderer can stay RGB-only until there is a concrete non-RGB preview
need. It should still consume the new float output from RGB animations rather
than requiring animations to return byte frames.

## Temporal Dithering

The current temporal dithering prototype operates on byte levels. It should not
be generalized in that form.

After the float migration:

- animation produces ideal `float32` light-channel values
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
2. Add byte encoding tests for clipping, rounding, dtype, shape, and
   light-channel count.
3. Port one simple animation and assert encoded byte output matches current
   behavior.
4. Port Hamiltonian and RandomWalk.
5. Port BiblioPixel animations one file at a time.
6. Update preview tests to assert equivalent encoded output.
7. Keep network packet tests byte-based.

Avoid testing implementation details like private helper order. Test visible
frame output and validation failures.

## Migration Sequence

1. Add float light-frame helpers and byte encoder while keeping current
   animation render type unchanged.
2. Change `Animation.render()` and `validate_frame()` to the float contract.
3. Update the runner to encode float RGB frames before Twinkly send.
4. Port Hamiltonian.
5. Port RandomWalk.
6. Port shared color helpers in `lyte/animations/colors.py`.
7. Port BiblioPixel animations one module at a time.
8. Update preview rendering to consume float frames.
9. Update `lyte test2` or replace its byte-level dither with float-output
   mapping once the migration is stable.
10. Add light-channel layout fields to `Device` or a device profile when the first
    non-RGB output needs them.
11. Search for remaining `NDArray[np.uint8]` animation render annotations,
    `dtype=np.uint8` frame construction, and direct RGB byte assignment.
12. Remove any temporary conversion helpers used only during migration.

Each commit should leave tests passing. If the port is too large for one safe
change, commit the helper/boundary work first, then commit animation families in
small batches.

## Open Questions

- Should animation constructor colors remain byte RGB tuples permanently, or
  should Lyte eventually expose user-facing float color constructors?
- Should `Device` itself own `light_channel_count` and light-channel labels, or
  should those live in a separate pixel-output profile?
- Should RGB animations declare their required color space explicitly before
  non-RGB outputs are implemented?
- Should out-of-range float frames fail at animation validation or only clip at
  output encoding? The plan recommends validation failure for render outputs and
  clipping only inside explicit output encoders.
- Should Twinkly empirical LUT compensation be configured per device, per model,
  or as a command-line option first?

## Additional Work Beyond the Prompt

None.

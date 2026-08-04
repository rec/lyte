# Temporal Dithering Plan

Lyte should support smoother slow fades on quantized RGB LED strips by spreading
integer brightness changes across pixels and time instead of advancing the whole
strip in lockstep.

The goal is not to create more than 8 bits of physical channel output. The goal
is to make the average strip brightness track the intended continuous fade more
smoothly when the viewer sees a group of LEDs rather than inspecting one pixel
at a time.

## Concepts

### Spatially Distributed Temporal Dithering

For a fade from one RGB frame to another, Lyte currently computes a quantized
RGB frame for each time step. During slow fades this can produce visible jumps,
because many pixels may cross the same integer channel boundary at the same
time.

Spatially distributed temporal dithering should instead advance pixel channels
in a dispersed order. For example, four pixels fading from 0 to 9 can produce
intermediate states like:

```text
0000
0001
0101
0111
1111
1112
...
9998
9999
```

The total light output changes more often, but each transport frame only changes
part of the strip.

### Error-Diffused Ordered Updates

Error-diffused ordered updates are the stricter version of the same idea. Each
transport frame compares the current integer output to the ideal floating-point
frame for the fade time. Pixel channels with the largest useful accumulated
error are advanced first, while a spatial order keeps adjacent LEDs from
changing together too often.

This should be optional at first. It is likely still cheap for Twinkly-scale
LED counts, but the simpler ordered temporal dither is easier to reason about
and should be tried first.

## Design

Add fade quantization as a renderer-level option, not as a new animation API.
Animations should continue to describe continuous or ordinary RGB output. The
playback path can choose how to quantize and schedule the generated frames.

Initial public concepts:

- `QuantizationMode.normal`: current behavior.
- `QuantizationMode.spatial_temporal`: dispersed pixel/channel updates.
- `QuantizationMode.error_diffused`: dispersed updates prioritized by current
  quantization error.

Potential configuration:

```text
target_fps: animation sampling rate
transport_fps: hardware send rate
quantization_mode: normal | spatial_temporal | error_diffused
```

`target_fps` describes how often the underlying animation is sampled.
`transport_fps` describes how often frames are sent to the device. Temporal
dithering only helps when `transport_fps` is higher than the rate at which the
ordinary quantized animation produces visible changes.

## Pixel Order

Precompute a stable dispersed LED order for each LED count:

```text
order[i] = (i * stride) % led_count
```

Choose `stride` so that:

- it is relatively prime to `led_count`
- it is close to `led_count / 2`
- it avoids obviously symmetric patterns when several choices are available

RGB channel order can be layered on top of this. The first implementation should
try pixel-major order:

```text
pixel 0 red
pixel 0 green
pixel 0 blue
pixel stride red
pixel stride green
pixel stride blue
...
```

If that produces visible color sparkle, try interleaving channel starts so that
red, green, and blue do not all use the same spatial phase.

## Spatial Temporal Algorithm

For each fade segment:

1. Compute the start and end RGB frames as `uint8`.
2. Compute the full list of scalar channel transitions needed to move from start
   to end.
3. Sort those transitions by fade progress and spatial channel order.
4. At each transport frame, apply every transition whose scheduled progress is
   less than or equal to the current fade progress.
5. Send the resulting integer RGB frame.

For a channel moving from `a` to `b`, each integer step has a threshold:

```text
threshold = step_index / abs(b - a)
```

The dispersed channel order breaks ties when many channels share the same
threshold.

This can be implemented with NumPy arrays and precomputed index arrays. The
per-frame work should be close to ordinary frame blending plus a small amount of
indexed assignment.

## Error-Diffused Algorithm

For each transport frame:

1. Compute the ideal floating-point RGB frame at the current fade progress.
2. Compare it to the current integer RGB frame.
3. Find channels whose current value should move toward the ideal value.
4. Apply a bounded number of updates, prioritizing the largest absolute error.
5. Break equal or near-equal errors with the dispersed spatial order.
6. Send the resulting integer RGB frame.

A simple version can avoid a full sort:

- build an eligibility mask for channels that need to move
- scan the precomputed spatial order
- update the first `k` eligible channels

A later version can use `np.argpartition` or `np.argsort` if the simple version
has visible artifacts. That should not be necessary until real hardware testing
shows the spatial-only version is inadequate.

## Integration Path

1. Add a pure frame-planning module under `lyte/animations/` or `lyte/` with no
   networking dependency.
2. Implement dispersed index generation and unit tests for coprime full-cycle
   ordering.
3. Implement spatial temporal dithering for a single fade between two RGB
   frames.
4. Add unit tests for monotonic channel movement, exact first frame, exact final
   frame, and expected unique frame counts on small examples.
5. Add an optional mode to `lyte test` so the current FPS fade test can compare
   normal fades and temporal dithered fades on the same lights.
6. Only after hardware testing, add error-diffused ordered updates behind the
   same quantization mode boundary.

## Testing

Unit tests should cover the pure planner, not Twinkly networking:

- generated LED order visits every LED exactly once
- no adjacent duplicate indices are produced
- first and final dithered frames equal the requested endpoints
- channels only move toward their target
- small examples produce expected intermediate frames
- unique frame counts increase compared with ordinary quantized fades where
  that is mathematically possible

Hardware testing should stay manual at first. The useful evidence is visual:

- whether slow fades look smoother
- whether dispersed updates look like shimmer or sparkle
- whether Twinkly internally collapses very high-rate frame updates
- whether higher transport rates produce more unique displayed states

## Risks

- Discrete LEDs may reveal the dither pattern instead of visually blending it.
- Twinkly may buffer, resample, or quantize frames internally.
- Very high transport rates may increase network load without improving output.
- RGB channels may need different ordering to avoid colored speckle during
  grayscale or near-grayscale fades.
- Error-diffused ranking may add complexity before it is visually justified.

## First Implementation Target

Start with spatially distributed temporal dithering only. Make it pure, small,
and testable. Then expose it in `lyte test` as a manual comparison mode against
the current fade behavior.

Do not add error-diffused ordered updates until the simpler mode has been tested
on real lights and shows a specific artifact worth fixing.

## Additional Work Beyond the Prompt

None.

# New LED Animation Ideas

## Goal

Expand Lyte's pixel animation library with effects that are visually distinct
from the current fills, gradients, wipes, chases, scanners, rainbows, waves,
pulses, twinkles, fireflies, searchlights, rain, random walks, and binary
patterns.

New animations should use the existing `Animation`, `Device`, and mutable
`State` contract. They render a C-contiguous `numpy.float32` RGB frame with
shape `(led_count, 3)` and must not perform device, network, MIDI, or timing
I/O themselves.

## Wearable Region Animations

These use the current named regions and their logical ranges. They do not need
physical coordinates and continue to work when Lyte scales a 250-LED authored
layout to the attached string.

### Region Relay

Pass a pulse through a configured sequence such as left leg, chest, right arm,
right leg, chest, and left arm. Each region can use the same local effect with a
phase offset, producing movement across the body without assuming geometric
adjacency.

### Mirrored Limbs

Render one child animation on both arms or both legs, with one side optionally
reversed. Modes should include synchronized, alternating, and delayed mirror.

### Chest Heartbeat

Render a paired fast-slow brightness envelope on the chest while maintaining a
lower ambient effect on the limbs. Rate, double-beat spacing, and recovery time
should be explicit rather than tied to frame count.

### Limb-to-Chest Bloom

Start dim motion at the distal end of each limb, move it toward the torso, and
finish with a broad chest bloom. This is a timed composition of region-local
wavefronts, not a claim about the garment's physical coordinates.

### Region Call and Response

Choose one region to display a short phrase of motion or color, then answer on
another region with a transformed phrase. Seeded selection can vary the pairing
while keeping previews and tests repeatable.

## Spatial Animations Deferred

Radial bursts, true spirals, gravity, body-height gradients, and nearest-point
propagation require stable per-LED 2D or 3D coordinates. The current wearable
model contains named logical regions and physical index ranges, not spatial
coordinates. These effects should not infer geometry from LED index or region
names.

## Additional work beyond the prompt

None.

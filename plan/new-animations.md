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

## Linear String Animations

These effects need only an LED index and can run on an ordinary Twinkly string
or inside a wearable region.

Implementation status: all effects in this section are available through
`lyte animate` and `lyte preview`. Their classes also expose the richer controls
listed below for Python and installation-file construction.

### Fire and Embers

Maintain a one-dimensional heat field. New heat appears near a configurable
origin, diffuses along the string, cools over time, and maps through a fire
palette. Occasional detached embers can travel beyond the main flame.

Useful controls: origin, cooling, diffusion, spark rate, wind direction,
palette, and seed.

### Aurora

Combine several slow bands of color whose positions, widths, and brightness
vary independently. Smooth noise should make the bands fold and drift without
the regular repetition of a sine wave or rainbow cycle.

Useful controls: palette, band count, drift speed, softness, intensity, and
seed.

### Ocean Current

Layer long, low-contrast waves moving at different speeds and directions. Add
rare bright crests so the result reads as water rather than the existing
single-frequency wave animation.

Useful controls: palette, wave count, speed range, crest rate, and turbulence.

### Interference

Add two or more moving periodic fields, then map constructive and destructive
interference to brightness or color. Changing their wavelengths slowly creates
moire-like motion across the string.

Useful controls: wavelengths, speeds, phase offsets, palette, and contrast.

### Palette Conveyor

Move a continuous, user-defined color gradient along the string. Unlike the
existing discrete color pattern, adjacent LEDs interpolate between palette
stops and the loop can ease, reverse, or pause.

Useful controls: palette, stop spacing, speed, direction, and interpolation.

### Confetti With Decay

Spawn short-lived colored points into a persistent frame. Each point fades over
its own lifetime, allowing bursts, sparse glitter, or dense confetti without
the frame-to-frame replacement used by `FireFlies`.

Useful controls: palette, spawn rate, lifetime, fade curve, width, and seed.

### Lightning Storm

Keep the string mostly dark, then generate irregular flashes containing a
bright core, dimmer neighbouring branches, and a short decaying afterglow.
Storms should group flashes into bursts separated by longer quiet intervals.

Useful controls: color, flash rate, burst size, branch width, afterglow, and
seed.

### Candle Bank

Divide the string into configurable zones, each with a warm base level and
independent low-frequency flicker. Rare dips and flares should avoid uniform
whole-string brightness changes.

Useful controls: zone size, base color, flicker amount, flare rate, and seed.

### Colliding Particles

Move several colored particles along the string with position and velocity.
Particles reflect at the ends and exchange velocity or emit a flash when they
collide. Trails can expose the path without turning the result into another
scanner.

Useful controls: particle count, speed range, radius, trail decay, collision
flash, palette, and seed.

### Expanding Ripples

Create paired wavefronts from one or more origins. Each event travels in both
directions, broadens, and fades. Events may be periodic or generated from a
seeded schedule; an input-reactive version can be added later.

Useful controls: origins, event rate, propagation speed, width, decay, palette,
and seed.

### Cellular Automaton

Treat each LED as a cell in a one-dimensional elementary cellular automaton.
Map cell age or recent state transitions to a palette rather than displaying
only binary on and off values.

Useful controls: rule number, initial density, generation rate, history decay,
palette, and seed.

### Reaction-Diffusion Strip

Simulate two interacting concentrations on a one-dimensional ring or bounded
line and map their difference to color. This can produce evolving spots and
bands that are less regular than procedural waves.

Useful controls: feed rate, kill rate, diffusion rates, simulation steps per
frame, boundary mode, palette, and seed.

### Packet Traffic

Generate groups of short pulses with headers, payloads, gaps, and occasional
acknowledgements moving in the opposite direction. This produces structured,
readable activity rather than uniformly random motion.

Useful controls: direction, packet rate, length range, error rate, colors, and
seed.

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

## Input-Reactive Variants

These should be implemented through the existing patch bindings and MIDI
lifecycle. The animation still receives resolved state and never reads MIDI
directly.

### Velocity Splash

A note-on creates a ripple whose brightness and width derive from note
velocity. Pitch class selects the palette color.

### Breath Bloom

CC 2 controls the size and brightness of a persistent bloom. Releasing breath
contracts the bloom smoothly instead of abruptly scaling a static frame.

### Pitch-Bend Travel

Pitch bend moves a focal point along a region or the whole logical string.
Breath controls its tail or halo, allowing one continuous gesture to control
both position and intensity.

### Note-Age Constellation

Represent the active note as a small set of points that separate and dim as the
note ages. A later note replaces the current constellation, matching Lyte's
current single-active-note MIDI contract.

### Patch Transition Morph

On a program change, crossfade from the current patch frame to the next patch
instead of replacing it immediately. The selector remains responsible for the
transition; individual animations remain independent.

## Spatial Animations Deferred

Radial bursts, true spirals, gravity, body-height gradients, and nearest-point
propagation require stable per-LED 2D or 3D coordinates. The current wearable
model contains named logical regions and physical index ranges, not spatial
coordinates. These effects should not infer geometry from LED index or region
names.

## Linear Animation Completion

The linear animations share behavior-focused tests for frame shape and type,
bounded output, deterministic seeded output, progression across frames, and
single-LED strings. Focused tests also cover persistent confetti decay, ripple
propagation, cellular rules, elapsed-time reaction-diffusion, and packet
acknowledgements.

The wearable-region and input-reactive sections remain possible future work.

## Additional work beyond the prompt

None.

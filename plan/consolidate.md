# Plan: consolidate LED animations into five families

Status and scope
================
This is a design proposal, not executable implementation. Assume the effects
in new-animations.md have been implemented. Organize those effects and the
existing catalogue together. The family names describe how an animation is
built; individual effect names remain useful presets and algorithms.

Consolidation should reduce duplicated rendering and composition logic without
forcing unrelated algorithms into one class with dozens of optional fields.
Use five families: Patterns, Fields, Events, Simulations, and Compositions.
These are catalogue and ownership boundaries first. Introduce shared base
classes only where there is actual shared behavior.

Common contract
===============
Every family implements the existing immutable Animation description and
initial_state(device)/render(device, state) lifecycle. Each playback instance
owns independent mutable State, including any child states and random generator.
The result remains finite, C-contiguous float32 RGB with shape (led_count, 3).
Transport encoding, physical wearable mapping, and device recovery stay outside
the animation graph.

Use consistent meanings for properties where they apply:

- Color: normalized RGB components in 0..1; a palette is an ordered color list.
- Brightness: a nonnegative gain, normally 0..1. A composition-level gain can
  control a whole graph without copying that setting into every child.
- Time: durations and lifetimes in seconds, event rates in events per second,
  periodic rates in cycles per second. FPS belongs to playback state.
- Space: position and width as fractions of the child's logical span. Physical
  LED ranges belong to placement; discrete cell counts remain integers.
- Motion: signed velocity in logical spans per second where motion applies.
- Randomness: an optional seed only for effects that use random state.

Do not add meaningless speed, palette, seed, or duration fields to every effect.
Explicitly distinguish elapsed-time effects from discrete simulation steps.
Preserve current output during reorganization; changes to legacy color units,
per-frame rates, clipping, or timing need their own documented conversion and
regression fixtures.

1. Patterns
===========
An explicit arrangement of colors, repeated or traversed along the string.
The defining data is a palette, ordered pattern, or discrete traversal rule.

Common properties: palette, repeat length, phase, direction, and traversal rate
where applicable. State is generally a phase, cursor, or counter.

Members:
- ColorFill, including black and single-color presets.
- ColorPattern and Alternates: repeated bands or alternating cells.
- ColorWipe and SaberBlade: progressive coverage of the span.
- GreyCode and Hamiltonian: retain their distinct discrete traversal algorithms.

Consolidation opportunities: share palette lookup and span traversal where
equivalent. Keep named algorithms separate when their sequence is distinctive.
The CLI off command still requests hardware off; black pixels are not an
equivalent replacement for that command.

2. Fields
=========
Compute color or intensity from logical position and time. Fields may use
smooth noise, but have no interacting population of particles or cells.

Common properties: palette or color, spatial scale, phase, temporal rate, and
contrast where applicable. State holds phase and any noise generator state.

Members:
- LinearGradient and LogGradient.
- Rainbow, RainbowCycle, LinearRainbow, and HalvesRainbow.
- Wave and moving Wave.
- ColorFade and ExponentialFade, as time-varying color/intensity fields.
- Palette Conveyor, Aurora, Ocean Current, and Interference.
- Candle Bank's local flicker field.
- Breath Bloom's underlying position/intensity field.

Consolidation opportunities: share gradient sampling, palette interpolation,
periodic phase calculations, and intensity envelopes. Where Aurora or Ocean
Current is assembled from independently renderable fields, its public preset
is a Composition using those Fields. Combining scalar terms inside one formula
alone does not require an animation graph.

Fading between colors is a Field. Fading between rendered animations is a
Composition.

3. Events
=========
Create visible objects or bursts with an onset, position, age, and lifetime.
Objects evolve independently; interactions that affect their evolution belong
in Simulations.

Common properties: color/palette, origin, width, lifetime, envelope, velocity,
and emission rate where applicable. State contains active events and any emitter
schedule. Some effects use a fixed population instead of an emitter.

Members:
- ColorChase, LarsonScanner, Searchlights, and PixelPingPong: moving objects.
- Pulse: the existing traveling pulse, not a whole-string breathing envelope.
- Twinkle, WhiteTwinkle, FireFlies, and Confetti With Decay.
- Rain: preserve its current accumulating colored-point behavior.
- Lightning Storm, Expanding Ripples, and Packet Traffic.
- Velocity Splash and Note-Age Constellation's underlying visible events.
- Pitch-Bend Travel's controlled focal point.

Consolidation opportunities: share envelope and trail calculations, event age,
and motion sampling. WhiteTwinkle can be a palette preset. Keep scheduling
differences explicit: random per-frame replacement, persistent deposits, and
finite-lived points do not become identical merely because all use dots.
Do not require a general particle engine for a single deterministic scanner.

4. Simulations
==============
The next state depends on the previous state through a stochastic process,
neighbour interaction, or evolving physical/numerical model.

Common properties: initialization/seed, update rate, and palette mapping.
Boundary behavior applies to models with spatial neighbours. Model-specific
parameters such as cooling, collision response, or automaton rule remain on
their respective definitions.

Members:
- RandomWalk: stochastic evolution of the existing state.
- Randomize and PartyMode: simple stochastic color processes.
- Fire and Embers: heat evolution, optionally composed with ember Events.
- Colliding Particles: interacting positions and velocities.
- Cellular Automaton and Reaction-Diffusion Strip.

Consolidation opportunities: share deterministic state initialization and
time-step handling where useful. Keep numerical solvers separate. A fixed
simulation update rate should be independent of output FPS; rendering samples
the resulting state. Specify work limits and test stability before adopting a
shared stepping helper.

5. Compositions
===============
A Composition is itself an Animation and can contain children from any family,
including other Compositions. It owns how children occupy space, combine their
RGB frames, and progress through time. Reuse one rendering implementation in
ordinary playback, previews, wearable patches, and installation pixel targets.

Common properties: ordered children, per-child playback state, and the concrete
operation's parameters. Use separate concrete composition models with relevant
properties, rather than one model containing every possible composition option.

Spatial composition
-------------------
Segments place child animations into disjoint logical ranges. Each child sees
a local Device of the allocated length. Gaps are black; overlapping placements
must use an explicit mix. Consecutive concatenation is a convenient form of the
same placement operation.

Consolidate SegmentAnimation, RegionLightPatch rendering, and concatenated
wearable rendering around this one operation. Wearable names resolve to logical
ranges before rendering, using the existing runtime LED-count scaling. Apply
the physical index map once after the complete logical frame is composed.

Mirrored Limbs is a segment composition with reversal of one child's logical
output. Synchronized copies use equal local times and deterministic initial
conditions; independent copies own independent state. Never advance the same
mutable child state twice to obtain two placements.

Mixing composition
------------------
Mix renders children over the same logical span and combines their frames.
Properties: children, nonnegative weights, and the defined combination rule.

The existing additive and weighted patches can share weighted-sum rendering:
additive mixing uses weights of one. Preserve the current clipping to 0..1 at
the mix boundary. Weights are not implicitly normalized, so reducing all
weights reduces brightness. Nested clipped sums must not be flattened if doing
so changes output.

Crossfade is a timed mix of two animations with weights (1-p, p), where p moves
from zero to one over a duration using an explicit easing curve. Both children
continue rendering during overlap. Transfer the incoming child's existing
state into continued playback so it does not restart after the fade.

Move the current random-playback crossfade calculation and patch-transition
morph rendering to this common operation. Selection of the next animation or
patch remains the caller's responsibility.

Temporal composition
--------------------
Sequence coordinates ordered children with start times, durations, and optional
crossfade overlaps. Each occurrence has its own state. A newly scheduled
occurrence starts at local time zero; continuing an already active child across
a transition retains its state. Delay and phase are explicit timing choices,
not hidden calls that advance an effect extra times.

Use it for Region Relay, Region Call and Response, and Limb-to-Chest Bloom.
Chest Heartbeat combines a timed intensity envelope on the chest with ambient
limb children. An intensity envelope or spatial reversal can wrap one child;
it is a composition operation even when there is only one child.

Wearable and reactive presets
============================
Wearable and MIDI-reactive are uses of the five families, not additional
rendering families. Existing layer names and performance patch names remain
presets built from the underlying algorithms and compositions.

- Region Relay: Sequence of spatially placed Events.
- Mirrored Limbs: Segments plus reversal and timing offsets.
- Chest Heartbeat: Segments plus intensity envelope and ambient children.
- Limb-to-Chest Bloom: Sequence of region-local Events and a chest Field.
- Region Call and Response: Sequence with selected regions and child presets.
- Velocity Splash: note velocity and pitch mapped to ripple Event parameters.
- Breath Bloom: breath mapped to Field extent and intensity.
- Pitch-Bend Travel: pitch bend mapped to Event position; breath to width/gain.
- Note-Age Constellation: note lifecycle controls an Event population.
- Patch Transition Morph: Crossfade between active patch animation graphs.

MIDI selection, note replacement, and control interpretation remain in the
patch layer. New parameter bindings may be needed for these variants; the
current binding schema does not automatically support arbitrary fields.
Ensure note-off and blackout terminate output under the established patch
lifecycle even while a transition is active.

Physical spatial effects remain dependent on a future coordinate model.
DMX programs retain their separate semantic values and universe encoder; these
five families organize pixel animations, including pixels in mixed installations.

Implementation order
====================
1. Catalogue the implemented effects under these families and capture existing
   behavior before moving or combining implementations.
2. Consolidate spatial placement and additive/weighted mixing from animation.py
   and midi.py into reusable Composition animations. Keep note handling in MIDI.
3. Implement common Crossfade state and use it for random playback and patch
   transitions; then add the temporal compositions required by wearable presets.
4. Group the remaining implementations into the four generator families. Merge
   only algorithms proven equivalent; express color/direction variations as
   presets. Replace obsolete rendering paths and update all their callers.
5. Standardize the applicable properties with explicit unit conversions and
   update CLI construction, patch configuration, previews, and documentation.

Validation should preserve individual effects and verify exact segment placement,
child-state independence, reversed output, weighted sums and clipping, crossfade
endpoints and continuation, note lifecycle behavior, and LED-count scaling.
Use seeded output for random effects and equivalent elapsed times at multiple
FPS values for time-based effects. Reuse the existing test framework.

Additional work beyond the prompt
================================
None. This file proposes the consolidation; it does not implement the refactor.

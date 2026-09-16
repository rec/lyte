# Remaining verification and feature proposals

## Physical rehearsal

Automated checks do not establish physical readiness. Rehearse with the actual
controllers, gateway, fixtures, and show configuration:

- **WLED and Twinkly:** selection, fades, master level, blackout, disconnection,
  and reconnection while healthy outputs continue.
- **Art-Net and DMX:** gateway delivery, fixture addressing, selection,
  disconnection, recovery, and fixture-specific blackout and shutdown. For the
  laser example, verify centred geometry at 64 and mode-only blackout; pixel
  fades, master level, and tests must not alter fixture channels.
- **showCo and lyte:** rehearse a short cue list forwards and backwards with
  physical output. Check that reconnecting shows current state without advancing
  or replaying a selection, including after an uncertain command reply.

Record observed results and any failures before declaring hardware readiness.

## Optional future features

These are proposals, not implementation commitments. Choose a milestone before
changing code or dependencies.

### Audio

- Live audio input, including device selection and reconnection. Review recs
  facilities before introducing another capture path; keep portable control
  declarations in uFor and acquisition in the runtime.
- Audio playback alongside previews or exports, with explicit synchronization
  and end-of-file behavior.
- Port the remaining synthetic reactive demonstrations to real audio controls.

### Show cues

- Per-cue transition durations and timed advancement in showCo.
- Synchronization with other show actions. Introduce a shared clock or timecode
  only for a concrete requirement; showCo remains the cue owner.

### Authoring and output

- Device-specific brightness and colour calibration at the physical output
  boundary, with a deliberate calibrated-preview mode. Define units and measure
  hardware before treating an estimated brightness limit as a power limit.
- Geometry-aware effects for measured installations: radial waves, height
  gradients, and nearest-neighbour propagation. Use declared coordinates, not
  guessed relationships between LED indexes.
- A before/after comparison view with a fixed playhead and seed.
- Perspective orbit controls and camera-based layout capture.
- Direct filesystem saving of editor changes, with an explicit overwrite policy.

The region-effect proposals in [new-animations.md](new-animations.md) remain a
separate catalogue. Wearable-specific additions are lower priority until there
is a scheduled use and measured hardware. Try existing composition operations
before proposing new effect implementations.

## Additional work beyond the prompt

None.

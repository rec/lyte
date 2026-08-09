# Tasks

## Personal Twinkly Reliability

- [x] Add an explicit Twinkly playback connection state: connecting, streaming,
  recovering, blacked out, and unknown. Report the state in logs rather than
  treating a failed off request as a successful blackout.
- [x] Refactor realtime playback setup so that any failure or interruption after
  switching to realtime mode still attempts to black out the device.
- [x] Replace terminal frame-send failure with a recovery loop: on a transient
  network, token, or device failure, stop producing visible output, attempt to
  re-discover and re-authenticate the device, restore realtime mode, and resume
  only after reconnection succeeds.
- [x] Apply the outage policy consistently: while a device is disconnected,
  Lyte's intended state is blackout. Do not retain or deliberately resend a
  last visible frame during recovery.
- [x] Make retry and transport functions return structured failure outcomes to
  playback code instead of calling `sys.exit` below the command boundary.
- [x] Add frame deadline accounting to normal animation playback and report
  late frames, missed deadlines, and recovery periods.
- [x] Add unit tests for failure after realtime setup, token loss during frame
  streaming, a multi-second recovery interval, and failed blackout cleanup.

## MIDI Input and Patch Playback

- [x] Implement selected Mido input-port and MIDI-channel filtering from
  `MidiIn` configuration.
- [x] Add `lyte patch play` to poll the selected input in arrival order, render
  the selected patch at its configured FPS, apply the physical map, stream the
  resulting Twinkly frame, and use the normal blackout cleanup path.
- [x] Make active-note identity explicit. A note-off must clear only the active
  note on the selected channel; a new note-on replaces that active note.
- [x] Implement the agreed CC 2 contract: values from the selected input and
  channel apply immediately to the active note's patch, persist until the next
  CC 2 or that note ends, and are processed in input arrival order.
- [x] Keep MIDI polling and patch rendering in the same playback loop initially
  so patch state cannot be mutated concurrently with rendering.
- [x] Add tests for channel filtering, note replacement, unrelated note-off,
  CC 2 persistence, CC 2 reset on note-off, and input-arrival ordering.

## Executable Wearable Patches

- [x] Replace `note_color`, `breath_speed`, `breath_mix`, and `pitch_speed`
  prose fields in `patches/wearable-breath.toml` with validated binding tables.
- [x] Implement pitch-class palette selection and the declared note, breath,
  mix, and positive pitch-bend mappings against mutable per-note patch state.
- [x] Compile a patch's declared blend policy into `BlendLightPatch` or
  `WeightedBlendLightPatch` rather than treating all multi-layer patches as an
  additive blend.
- [x] Allow each declared layer to select its own logical regions so a patch can
  express chest-only and limb-only layers without creating artificial layer
  names.
- [x] Apply `WearableSpec.physical_map` between logical patch rendering and
  Twinkly encoding in patch playback.
- [ ] Permit the locator command to use a provisional map, but reject
  performance patch playback until the physical map is marked `measured`.
- [ ] Mark the existing thirty-two entries as experimental in list output until
  their declared controls and visual behavior are executable. Do not treat
  their current names as stable visual commitments.
- [ ] Add tests that each executable binding changes the intended target and
  that compiled patch playback maps logical regions to physical indexes.

## Current Contracts and Documentation

- [ ] Update `doc/api-plan.md` and `plan/dmx.md` to state the current
  `float32` RGB frame contract, current Python version, and which parts remain
  proposals rather than runtime behavior.
- [ ] Update `README.md` to describe Lyte as a dependency-using personal
  Twinkly player with experimental patch support, not a dependency-free proof
  of concept.
- [ ] Keep RGB-to-other-light-channel conversion deferred until the intended
  BiblioPixel-derived color model is specified. Do not add a generic RGBW or
  non-RGB conversion policy before that decision is complete.

## Shared Playback and DMX Preparation

- [ ] Extract Twinkly playback lifecycle, timing, recovery, and blackout policy
  from animation selection so it can become one track in a later show runner.
- [ ] Define a small synchronous track runner for the reliable Twinkly player:
  it owns a monotonic clock, one render state, one output lifecycle, and
  observability. Do not generalize its payload type yet.
- [ ] Add DMX core types separately from pixel frames: universe, fixture
  profile, fixture instance, fixture-level values, and validated universe
  buffers.
- [ ] Add fixture-profile encoding tests before any DMX transport.
- [ ] Add Art-Net packet encoding and sender tests against validated DMX
  universe buffers.
- [ ] Extend the track runner only after Twinkly recovery is reliable, so a
  Twinkly outage can black out that track without stopping Art-Net or later
  protocol tracks.

## Show Files

- [ ] Implement show-file graph construction and playback for trusted local
  Python implementation paths. Continue to treat show files as trusted machine
  configuration.
- [ ] Create device-local playback state for each run target so one immutable
  animation description can run independently on multiple outputs.
- [ ] Defer non-RGB and multi-protocol show-file device kinds until their
  drivers and track lifecycle exist.

## Additional work beyond the prompt

None.

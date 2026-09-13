# Multiple Twinkly Strings

## Goal

Extend one installation document so the same physical strings can run either:

- one animation as a single logical string spanning both physical strings; or
- independent animations, one per physical string.

Patch selection must not require a process restart or a second installation
file.

The initial show has two Twinkly strings. The design must not depend on their
configured LED counts: device discovery remains authoritative and all logical
frames scale to the connected outputs.

## Terms

- A **physical string** is one configured Twinkly target with one host and one
  realtime output connection.
- A **string group** is an ordered list of physical strings. It is a virtual
  output, never a network device.
- A **patch** is one selectable assignment of pixel programs to physical
  strings or string groups.
- A **group program** renders one logical RGB frame for the whole group.

## Installation Model

Keep `[twinkly.<name>]` as the definition of each physical device. Add
`[strings.<name>]` for virtual groups and `[patches.<name>]` for the selectable
patches.

```toml
[twinkly.left]
host = "192.168.1.17"

[twinkly.right]
host = "192.168.1.18"

[strings.pair]
members = ["left", "right"]

[programs.pair_chase]
kind = "pixel"
selector = "show:/pair-chase.toml"
output = "light"

[programs.left_waves]
kind = "pixel"
selector = "show:/left-waves.toml"
output = "light"

[programs.right_sparks]
kind = "pixel"
selector = "show:/right-sparks.toml"
output = "light"

[patches.pair_chase]
pair = "pair_chase"

[patches.separate_waves_and_sparks]
left = "left_waves"
right = "right_sparks"

initial_patch = "pair_chase"
```

The keys in a patch are output names. They may name a physical Twinkly target
or a string group. Program names resolve through the existing `[programs]`
table. A group patch and a separate-string patch are peers in one patch list.
The current `[run]` table is replaced by patches because it cannot express a
selectable patch collection.

## Validation

Validate the complete installation before opening any output:

1. A string group has at least one member, names only configured Twinkly
   targets, and does not repeat a member.
2. A patch names only physical targets or groups and assigns only pixel programs
   to them.
3. Within one patch, every physical string appears exactly once, either directly
   or through one group. This prevents two renderers from sending to the same
   controller and prevents accidental dark strings.
4. `initial_patch` names a declared patch.
5. A group program has RGB drive components, as existing Twinkly programs do.

No validation compares an authored layout count with a configured or detected
device count. Count differences produce warnings and scaling at output time.

## Rendering a Group

Opening a physical string discovers its actual LED count. A group records the
ordered member counts and their total.

For a group program:

1. Render one authored logical frame.
2. Resample that frame once to the sum of the connected member counts.
3. Split the resampled frame into contiguous slices in `members` order.
4. Apply each member's physical wiring to its slice, then send that slice to
   the corresponding Twinkly connection.

This makes a 250-plus-500 installation act as one 750-pixel logical strip. If
the discovered total differs from the score layout, scaling preserves the
relative position across the whole pair rather than sending a complete scaled
copy to each string.

For a direct physical-string program, retain the existing behavior: render its
own frame, apply its own wiring, then resample to that string's discovered
count.

Group ordering is deliberately explicit. Reversing a physical string belongs in
that target's wiring definition, not by reversing group membership or score
coordinates.

## Patch Selection

Turn the installation runner into a Reccy service with one patch-selection
interface:

- `select_patch` accepts one declared patch name and queues it for the next
  output scheduler boundary.
- `status` returns the active patch, queued patch, per-string connection state,
  detected count, frame count, output failures, and group membership.

The service prepares every program referenced by the installation while loading
the document. Selecting a patch activates fresh renderer state for its programs
at one scheduler boundary. This makes transitions deterministic and ensures two
separate programs begin together when a patch is selected.

The first implementation changes patches on the next frame without an implicit
fade. This plan does not add lifecycle commands.

## Failure Behavior

Physical connection and retry behavior remains owned by `TwinklyTrack`.

- In a separate-string patch, a failed string is reported independently and healthy
  strings continue.
- In a group patch, failure of any member is reported against both the member
  and the group. Its existing connection recovery remains responsible for
  restoring output.
- If recovery finds a different LED count, recompute the group total and slice
  boundaries, warn through Reccy logging, and continue scaled output.
- A changed MAC remains an identity failure and does not silently redirect
  output to another controller.

## Implementation Steps

1. Replace `InstallationFile.run` with `initial_patch`, string-group, and patch
   data classes. Update TOML parsing and validation.
2. Separate reusable physical Twinkly connections from the active render
   assignments so no patch switch reconnects healthy devices.
3. Add a group renderer that rescales one frame to the discovered group total,
   partitions it, and dispatches per-member frames.
4. Add patch selection to the installation scheduler and expose the selected
   patch through Reccy RPC and status.
5. Update the installation CLI to start the service, and retain a bounded
   foreground duration option for setup tests.
6. Add tests for group validation, a 250-plus-500 partition, count changes on
   recovery, same-boundary patch selection, independent-patch failure isolation,
   and group failure reporting.
7. Add a two-string example installation and document the physical verification
   procedure: locator each string, verify group direction, and test both
   patches.

## Non-Goals

- Concatenating strings at the Twinkly protocol level.
- Dynamic discovery of unnamed show devices.
- Crossfades between patches in the first implementation.
- DMX patch selection. This plan defines the pixel-string model first; DMX can
  join the same patch selection mechanism only after its dynamic-program model
  exists.

## Additional work beyond the prompt

None.

# Multiple Twinkly Strings

## Goal

Extend one installation document so the same physical strings can run either:

- one animation as a single logical string spanning both physical strings; or
- independent animations, one per physical string.

Animation selection must not require a process restart or a second installation
file.

The initial show has two Twinkly strings. The design must not depend on IP
addresses, user-entered hardware identifiers, or configured LED counts. Device
discovery remains authoritative and all logical frames scale to the connected
outputs.

## Terms

- A **physical string** is one named Twinkly target selected from discovered
  devices and connected through one realtime output connection.
- A **BoundAnimation** is one top-level Ufor animation bound to this
  installation's physical strings. In the installation document, these are
  simply listed under `[animations]`.

## Installation Model

Keep `[twinkly]` as the definition of named physical strings. Its values are
`gestalt` selectors, not network addresses. Add `[animations.<name>]` for
selectable bound animations.

```toml
[twinkly]
left = { product_name = "Dots" }
right = {}

[animations.foo_bar]
selector = "show:/pair-chase.toml"
outputs = { animation_output = ["left", "right"] }

[animations.separate_waves_and_sparks]
selector = "show:/separate-waves-and-sparks.toml"
outputs = { first_output = ["left"], second_output = ["right"] }

initial_animation = "foo_bar"
```

Each `outputs` entry maps one named animation output to an ordered list of
physical strings. A one-item list sends that output to one string. A longer
list makes those strings one logical output for that animation, in list order.
The installation document attaches no parameters or other animation behavior.
The current `[run]` table is replaced by `[animations]` because it cannot
express a selectable collection.

## Device Assignment

At startup, Lyte repeatedly broadcasts for Twinkly devices, obtains `gestalt`
from every response, and assigns discovered devices to the names under
`[twinkly]`. An IP address exists only for the duration of that connection and
is never written to the installation document.

A selector may contain any supported string `gestalt` field:

- `device_name`
- `product_name`
- `product_code`
- `hardware_id`
- `firmware_family`
- `led_profile`

Each selector value is a case-insensitive substring match. Multiple fields in
one selector are combined with AND. The example assigns `left` to the only
device whose `product_name` contains `Dots`; the empty `right` selector then
receives the one remaining discovered device.

Assignment is a one-to-one global match, not a first-match loop. Lyte starts
only when every configured name has exactly one complete assignment and no
device is assigned twice. While strings are still being plugged in or Wi-Fi is
settling, it keeps discovering and logs the unmatched names and safe device
descriptions. It never selects an arbitrary device to resolve ambiguity.

After an assignment succeeds, the connection retains the discovered MAC and
uses it to verify recovery. The MAC is discovered and retained by Lyte; the
user never enters or copies it.

There is one unavoidable limit: two devices with indistinguishable `gestalt`
data cannot be given meaningful different names automatically. Separate
left/right animations require at least one observed distinction, such as product
name, product code, or LED profile. A multi-string output can still use
indistinguishable devices when their physical order does not matter.

## Validation

Validate the complete installation before opening any output:

1. A Twinkly selector uses only supported string `gestalt` fields.
2. An output binding names one selected RGB drive output and a non-empty,
   ordered list of configured physical strings.
3. Each BoundAnimation binds only RGB drive outputs named by its selected score.
4. Within one BoundAnimation, every physical string appears exactly once across
   its output lists. This prevents two renderers from sending to the same
   controller and prevents accidental dark strings.
5. `initial_animation` names a declared animation.

No validation compares an authored layout count with a configured or detected
device count. Count differences produce warnings and scaling at output time.

## Rendering Bound Outputs

Opening a physical string discovers its actual LED count. A bound output records
the counts of its ordered physical strings and their total.

For an output bound to multiple strings:

1. Render one authored logical frame.
2. Resample that frame once to the sum of the connected string counts.
3. Split the resampled frame into contiguous slices in output-list order.
4. Send each slice to its corresponding Twinkly connection.

This makes a 250-plus-500 installation act as one 750-pixel logical strip. If
the discovered total differs from the score layout, scaling preserves the
relative position across the whole pair rather than sending a complete scaled
copy to each string.

A binding with one physical string uses the same algorithm with one slice.
Ordering is deliberately explicit in the list; it defines the logical direction
of a multi-string output.

## Animation Selection

Turn the installation runner into a Reccy service with one animation-selection
interface:

- `select_animation` accepts one declared animation name and queues it for the
  next output scheduler boundary.
- `status` returns the active animation, queued animation, per-string connection
  state, detected count, frame count, output failures, and output bindings.

The service prepares every animation referenced by the installation while loading
the document. Selecting an animation activates fresh renderer state for its
named outputs at one scheduler boundary. This makes transitions deterministic
and ensures separate outputs begin together when an animation is selected.

The first implementation changes animations on the next frame without an
implicit fade. This plan does not add lifecycle commands.

## Failure Behavior

Physical connection and retry behavior remains owned by `TwinklyTrack`.

- In a separate-string animation, a failed string is reported independently and
  healthy strings continue.
- In a multi-string output binding, failure of any string is reported against
  that string and its bound animation. Its existing connection recovery remains
  responsible for restoring output.
- If recovery finds a different LED count, recompute the bound-output total and
  slice boundaries, warn through Reccy logging, and continue scaled output.
- A changed MAC remains an identity failure and does not silently redirect
  output to another controller.

## Implementation Steps

1. Replace host-based `TwinklyTargetSpec` and `InstallationFile.run` with
   `gestalt` selector, `initial_animation`, and BoundAnimation data classes.
   Update TOML parsing and validation.
2. Add discovery-and-assignment with one-to-one matching, retry logging, and
   post-assignment MAC verification. Do not persist IP addresses.
3. Separate reusable physical Twinkly connections from the active render
   assignments so no animation switch reconnects healthy devices.
4. Add bound-output rendering that rescales one frame to each output binding's
   discovered total, partitions it, and dispatches per-string frames.
5. Add animation selection to the installation scheduler and expose the
   selected animation through Reccy RPC and status.
6. Update the installation CLI to start the service, and retain a bounded
   foreground duration option for setup tests.
7. Add tests for selector matching, unambiguous assignment, the single
   remaining-device fallback, ambiguous-device reporting, a 250-plus-500
   partition, count changes on recovery, same-boundary animation selection,
   independent-output failure isolation, and multi-string failure reporting.
8. Add a two-string example installation that starts from automatic discovery
   and assignment without a setup action.

## Non-Goals

- Concatenating strings at the Twinkly protocol level.
- Selecting between indistinguishable physical strings without an observable
  `gestalt` difference.
- Crossfades between animations in the first implementation.
- DMX animation selection. This plan defines the pixel-string model first; DMX
  can join the same animation selection mechanism only after its dynamic
  animation model exists.

## Additional work beyond the prompt

None.

# Remaining lyte issues

The original 28-item review remains in Git history. Software fixes completed
since then have been removed here. The physical checks are grouped at the end
for the show rehearsal.

## Final API and operator-language review

1. **Installation command shape.** `lyte installation` exposes `duration`,
   `record_input`, and a config path on actions that ignore them. Decide together
   whether to reject irrelevant combinations or split actions into distinct
   command types. Review the generated help before changing the public CLI.

## Accepted runtime tradeoff

**Preserve score timing after a stall.** The delivery scheduler skips missed
   send slots in constant time, but stateful scores still execute every missed
   logical tick. This follows the requested timing policy. An exceptionally long
   stall can therefore cause delayed output while score state catches up; the
   existing catch-up metric makes that visible. Changing this would require an
   explicit decision to skip or approximate score state.

The editor still permits up to 32 MiB of raw preview frames. Its JSON response
now streams without another full server-side copy, but base64 frames and browser
state use more memory than the raw limit. The established preview limit was not
lowered without evidence that a normal score exceeds host resources.

## Assessed without a separate refactor

The largest source and test files are long, but size alone did not justify
moving public effect names or splitting cohesive interactive tools before the
show. New reliability tests went into a separate module instead of enlarging
`tests/test_installation.py`. The animation and CLI-help tests cover distinct
behavior; no redundant group was found to delete. lyte's retry helper executes
and logs operations, while reccy's retry schedule only decides timing; merging
them now would change retry semantics without fixing an observed failure.

## Additional work beyond the prompt

None.

## Physical show rehearsal

2. **Identify the actual Strings controller.** In
   `patches/showco-installation.toml`, Dots is selected by a product-name
   substring and Strings is the remaining device. Observe each controller's
   gestalt and add a distinguishing selector for Strings. Rehearse discovery
   with both controllers and any other Twinkly device that may be present.

3. **Verify fixture stop and network failure behavior.** Check the laser's
   authored blackout mode with physical output while preserving its centred
   geometry. Check Twinkly, WLED, and Art-Net blackout, stop latency, link loss,
   reconnection, and mixed-output continuity on the show hardware. Software
   success and unacknowledged UDP sends cannot prove visible output or safety.

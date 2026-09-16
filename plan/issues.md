# Repository issues

Reviewed 2026-09-16. This is a source review, not a hardware qualification or a
claim that every file has been exhaustively audited. Findings below distinguish
code defects, user-facing traps, and design work. No application, service, or
test suite was run for this documentation-only review.

Prioritize output safety, playback timing, data loss, and editor correctness.
Suggested checks describe future verification, not tests already performed.

## Bugs and consequential user traps

### 1. Device queries and setting changes turn the lights off

**Fixed 2026-09-16.**
[run_twinkly_command](../lyte/twinkly/command.py) now performs the requested
action without sending an additional off request. Existing command tests verify
that getters and setters do not invoke blackout cleanup. Playback retains its
own shutdown handling. Actual device behavior still needs hardware verification.

### 2. Installation playback ignores the score's declared frame rate

**Fixed 2026-09-16.** Installation rendering samples each binding at elapsed
monotonic time using its exact declared rate. Slower scores hold their last
frame; faster scores advance through every intervening tick to preserve state.
Selection and MIDI note restarts begin a fresh timeline. Tests cover differing
send rates, delayed frames, and note restarts.

### 3. Authoring embeds unescaped score metadata inside a script

**Fixed 2026-09-16.** Authoring now uses the standalone preview's `safe_json`
helper when embedding the catalogue. A regression test checks that a malicious
score title cannot close the script and introduce another script element.

### 4. Different render selectors can overwrite the same movie

**Fixed 2026-09-16.** Batch export preflights sanitized filenames, including
case-only collisions, and refuses existing destinations before rendering any
score. ffmpeg uses `-n` so files appearing after preflight are not overwritten.
Tests verify name collisions and preservation of existing exports.

### 5. The editor's Next button does not advance

**Fixed 2026-09-16.** Next advances one frame. A focused JavaScript check
executed the actual event handler and frame-selection function, including the
last frame with looping enabled and disabled.

### 6. Preview requests can leave stale or misleading results onscreen

**Fixed 2026-09-16.** Preview requests clear stale frames, check freshness after
body decoding, reset the playback clock on success, and preserve visible HTTP
and network errors. A focused JavaScript check exercised out-of-order body
completion, failed requests, and stale-frame clearing using the actual functions.

### 7. MIDI mappings can fail only after hardware starts

**Fixed 2026-09-16.** Preparation validates mapped endpoints or table values
against public parameter bounds and exercises the renderer's live-update
checks before discovery. Non-finite mappings and construction-only targets
produce errors naming the selector, output, and control. Tests cover invalid
ranges, tables, non-finite values, and a real construction-only effect target.

### 8. Discovery can wait forever before duration and RPC control apply

**Fixed 2026-09-16.** Installation TOML now accepts a positive, finite
`startup_timeout` (default 30 seconds) for discovery and identification. Scans,
HTTP identification retries, and retry sleeps share the deadline. Ambiguous
assignments fail immediately; Ctrl-C remains available during foreground
startup. Authentication/output setup keep their existing bounded retries.
Playback duration starts after outputs are ready. Focused tests use a fake
clock to verify timeout handling, ambiguity, and independent playback duration.

### 9. Two daemons claim the same service identity

**Fixed 2026-09-16.** Retired the legacy wearable daemon, its command,
configuration, and dedicated tests. The installation runtime is the sole
service owner. Wearable scores and `lyte patch` remain. Shared light-test
coverage was preserved, and the unused daemon MIDI replay helper was removed.
The guide describes replacement of old installed service definitions.

Source audit: showCo deployment and provisioning already use
`lyte installation install`. Installed services were not changed.

### 10. Test completion and blackout terminate the installation

**Fixed 2026-09-16.** Light tests resume the selected animation on its elapsed
timeline. Blackout cancels pending selection/tests and keeps sending black until
an animation is selected; tests are rejected during blackout. RPC status exposes
`blackout`. Only `stop` terminates playback. Tests verify resumption, blackout
persistence, cancellation, reselection, and explicit stopping.

### 11. Queued program changes collapse within one frame

**Fixed 2026-09-16.** Preserved the documented cycling policy: every program
change advances from the queued selection, or from the active selection when
nothing is queued. Program numbers remain ignored. A burst regression verifies
two advances, wraparound, and the applied selection.

### 12. MIDI note ownership ignores channel on release

**Fixed 2026-09-16.** Preserved latest-note priority while restricting note
release, breath, and pitch bend to the active note's channel. Tests cover
same-pitch notes on different channels, velocity-zero releases, foreign-channel
controls, and controls/releases from the owning channel.

### 13. ffmpeg cleanup is incomplete on exceptional export paths

**Fixed 2026-09-16.** Movies are encoded in a temporary directory beside the
output and published without overwriting an existing destination only after
ffmpeg succeeds. Failed exports are discarded. Every encoder is waited for;
an interrupted input kills the encoder first, and broken-pipe cleanup cannot
hide a rendering error. Tests cover renderer, write, close, encoder-exit, and
publication failures as well as success.

## Inefficiencies and editor limitations

### 14. Device assignment enumerates every ambiguous solution

**Fixed 2026-09-16.** Assignment search stops exploring once a second valid
solution proves ambiguity. Existing assignment tests cover unique, missing,
and ambiguous matches.

### 15. Slider movement starts overlapping full renders

**Fixed 2026-09-16.** Slider updates debounce for 150 ms and keep at most one
browser request in flight, with only the latest pending values retained. The
server rejects concurrent preview renders from other tabs with a visible busy
response. Preview generation rejects more than 10000 frames or 32 MiB of raw
frame data before rendering. Python checks cover workload limits; focused
JavaScript checks cover debounce, single-flight requests, and stale results.

### 16. Batch export repeatedly reloads the same library

**Fixed 2026-09-16.** Batch export passes its loaded library to every animation
preparation. Parsing and diagnostics occur once per batch. Dispatch tests
verify that every export receives the same library instance.

### 17. Editor downloads do not form a cumulative editing session

The operation, timing, and field endpoints in [authoring.py](../lyte/authoring.py)
each read the original source; successful downloads do not update the session's
library, tree, or preview. Editing timing and then fields produces independent
files, not one combined edit. Replacement templates likewise are not previewed
as pending changes.

This is a documented download-based boundary, but a significant trap for an
app presented as an editor. Make it explicit in the UI or plan a coherent
working-document model. Do not silently add persistence as part of another fix.

### 18. Spatial preview coverage remains incomplete

[plan/editor.md](editor.md) still requests a two-dimensional layout check.
Both HTML preview and authoring simply take the first two coordinates, so
three-dimensional layouts collapse onto XY without a selectable projection.
[doc/guide.md](../doc/guide.md) records a one-dimensional manual check only.

Add a concrete 2D verification example when doing this milestone, and state
whether 3D projection is supported. Do not treat prior browser checks as
coverage of the Next-button bug or all transport boundary behavior.

## Naming, documentation, and structure

### 19. Public command and option names hide their purpose

[cli.py](../lyte/cli.py) exposes `test`, `test2`, `verify`, and `black-floor`;
`test2` in particular does not communicate temporal dithering. `show` only
validates/prepares a score, whereas `animate` actually plays it.
`--output` selects a score output in `animate`/`show`, but a destination
directory in `render`; preview uses a positional destination and
`--light-output` for the score output.

Choose clearer names and consistent output terminology before expanding the
CLI. These are interface changes requiring a deliberate decision, not license
for a broad rename in an unrelated task.

### 20. README overstates installation transport support

The opening of [README.md](../README.md) advertises mixed Twinkly and Art-Net
installation playback. [installation.py](../lyte/installation.py) builds
Twinkly outputs only, and [doc/guide.md](../doc/guide.md) correctly says DMX,
Art-Net, and WLED are separate primitives. Align the capability summary with
what users can actually run. Integration is unfinished product work, not an
existing feature just because the transport classes exist.

### 21. Project spelling is inconsistent

README, guide, handover, plan text, and the authoring title still use `Lyte`,
`Ufor`, and `Reccy`. Use the requested display spellings: lyte, streamO, recs,
uFor, reccy, tuney, enge, showCo. Keep real import paths, filenames, and external
identifiers accurate; display capitalization is not a request to rename code.

### 22. Several modules combine too many responsibilities

At review time, [fps_test.py](../lyte/fps_test.py) has 970 lines,
[installation.py](../lyte/installation.py) 851,
[authoring.py](../lyte/authoring.py) 770, [patches.py](../lyte/patches.py) 754,
and [wled.py](../lyte/wled.py) 615. Counts alone are not defects, but these files
combine distinct responsibilities. Authoring embeds compressed HTML/CSS/JS
alongside validation and HTTP handling; installation combines schema, discovery,
assignment, output, MIDI, RPC, and scheduling. The long JavaScript lines make
review and focused browser testing especially difficult.

Split along demonstrated boundaries when those areas are next changed. Avoid
creating one-line modules or reorganizing the entire repository just to reduce
counts. No directory inspected warrants a split based on entry count alone;
cohesion and navigation matter more than an arbitrary limit.

### 23. One cheap test is disabled by an expensive-test gate

[tests/test_hamiltonian.py](../tests/test_hamiltonian.py) applies a module-wide
opt-in skip to both the sequence check and the tiny bad-transition helper
check. The latter does not need a full Hamiltonian sequence. Narrow the gate
if this test support is retained; normal green test totals currently include
neither check.

## Additional work beyond the prompt

None. This document records findings and proposed follow-up only. No fixes,
API changes, dependency changes, or subsystem removals are included.

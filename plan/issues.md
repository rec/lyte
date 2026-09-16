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

**User-facing operational trap.**
[discover_assignments](../lyte/installation.py) retries missing and ambiguous
assignments indefinitely. `build_service` performs discovery before the service
starts; `run(duration)` creates its deadline afterward. Thus `--duration 10`
does not bound discovery, and the runtime RPC stop path is unavailable while
waiting. A permanently ambiguous configuration is retried like a temporary
missing device.

Document or revise startup timeout semantics, distinguish ambiguity from
absence, and provide an interruptible startup policy. Do not describe
`--duration` as a bound on total command runtime in its current form.

### 9. Two daemons claim the same service identity

**Confirmed architectural conflict.**
[LyteMidiDaemon](../lyte/daemon_runtime.py) and
[InstallationService](../lyte/installation.py) both use `name = 'lyte'` and
[the same service specification](../lyte/service.toml), but expose different
selection commands and status models. `lyte daemon` and `lyte installation`
look like independent services while installation and RPC identity are shared.

Decide which runtime remains. Retirement of the wearable subsystem has been
discussed, but is not authorized by this issues list. Audit showCo callers and
installed service commands before any removal.

### 10. Test completion and blackout terminate the installation

**Behavior requiring an explicit product decision.**
[InstallationService.rpc_response and _test_frames](../lyte/installation.py)
treat both `blackout` and `stop` as termination requests. A completed RPC light
test also sets the stop event instead of resuming the selected animation.
A user expecting a temporary test or reversible blackout loses playback.

Decide whether this is intentional and document it prominently, or distinguish
pause/blackout/test from service termination. Verify the chosen post-test state.

### 11. Queued program changes collapse within one frame

**Confirmed edge case.**
[_receive_midi](../lyte/installation.py) computes the next animation from the
active name, ignoring an already queued name. Several program-change messages
processed before selection is applied all select the same next animation.
Their program numbers are ignored as well; that cycling policy is documented,
but callers may expect MIDI program selection semantics.

Define whether messages represent individual advances, direct program numbers,
or intentionally coalesced requests. Verify a burst of two messages.

### 12. MIDI note ownership ignores channel on release

**Conditional bug.** [MidiPerformance.receive](../lyte/runtime_control.py)
records the note-on channel but matches note-off only by pitch. If the input
admits multiple channels, another channel's note-off can release the active
note. Breath and pitch messages also lack active-channel matching.

Define multichannel ownership and verify same-pitch notes on different
channels. A fixed input-channel filter reduces exposure but does not resolve
the shared model's behavior.

### 13. ffmpeg cleanup is incomplete on exceptional export paths

**Confirmed resource-management gap.**
[render_animation](../lyte/render.py) waits for ffmpeg only on the successful
write path. Rendering errors or broken pipes close stdin without reliably
waiting for the child. Closing a buffered pipe in `finally` can also raise
another error and obscure the original failure. Partial movies are left at
the final destination.

Ensure every launched child is reaped and decide how failed outputs are
identified or published. Verify a renderer exception and early ffmpeg exit.

## Inefficiencies and editor limitations

### 14. Device assignment enumerates every ambiguous solution

[assign_twinkly_devices](../lyte/installation.py) accumulates all complete
assignments merely to distinguish zero, one, or multiple solutions. With N
indistinguishable devices and N empty selectors this grows as N factorial.
Stop once a second solution proves ambiguity. This needs no general-purpose
constraint solver.

### 15. Slider movement starts overlapping full renders

Every slider input in [authoring.py](../lyte/authoring.py) sends a new request.
The threaded server renders the entire preview for each request; request IDs
only discard some browser results and do not prevent server work. A long
preview or rapid drag can create substantial CPU and memory pressure.

Coalesce slider updates and bound concurrent preview work. Both authoring and
[encoded_frames](../lyte/preview/document.py) materialize every base64 frame;
preview size grows with duration, FPS, and light count, with additional decoded
copies in the browser. Expose or bound the intended preview workload.

### 16. Batch export repeatedly reloads the same library

[run_render](../lyte/render.py) reads the library for selection, then each
`render_animation` calls `show.prepare_animation`, which reads it again.
Large batches repeat parsing and diagnostics, and source edits during a batch
can mix library versions. Reuse the already loaded library for the batch.

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

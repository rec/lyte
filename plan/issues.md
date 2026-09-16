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

**Fixed.** Validated edits accumulate in memory. Every edit rebuilds the working
library and catalogue before committing it, and the browser refreshes its tree
and preview. Invalid edits leave the previous working copy intact. Downloads
retain comments and combine prior edits; source files remain unchanged. The UI
explains session lifetime and the need to download each changed score.

### 18. Spatial preview coverage remains incomplete

**Fixed.** Added a concrete 3×3 layout fixture and visually verified all nine
pixels in the browser. The guide now explicitly describes XY projection and
the absence of a selectable 3D view. Removed the completed editor plan.

## Naming, documentation, and structure

### 19. Public command and option names hide their purpose

**Fixed.** Commands are now `fps-test`, `dither-test`, `verify-output`,
`calibrate-black`, and `validate`. Score outputs use `--light-output` and file
destinations use `--output`, including preview. Updated examples, dispatch
checks, and the complete CLI help regression. Old command names are removed.

### 20. README overstates installation transport support

**Fixed.** README now describes Twinkly installation playback and explicitly
identifies WLED DDP and DMX/Art-Net as separate primitives.

### 21. Project spelling is inconsistent

**Fixed.** Display text, documentation, docstrings, and service labels use lyte,
uFor, and reccy. Real class names, imports, and identifiers remain accurate.

### 22. Several modules combine too many responsibilities

**Fixed.** Split the demonstrated responsibilities into focused modules:
`authoring_http.py` handles HTTP, `authoring_template.py` holds readable browser
markup and JavaScript, `installation_config.py` handles installation TOML and
expressions, `patch_config.py` handles patch schema/loading,
`diagnostic_frames.py` generates diagnostic frames, and `wled_output.py` owns
DDP transport. Updated callers, including Python-authored wearable scores;
there are no compatibility re-exports. Remaining runtime modules retain their
cohesive orchestration responsibilities. Existing tests and focused browser
transport/queue checks verify the moved code.

### 23. One cheap test is disabled by an expensive-test gate

**Fixed.** Only the full Hamiltonian sequence test is opt-in. The inexpensive
bad-transition check now runs in the normal suite.

## Additional work beyond the prompt

None. All listed issues have been resolved.

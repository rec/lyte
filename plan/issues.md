# lyte issues and review notes

This is a source and test review, not a claim of physical show validation. Priorities
reflect likely impact on a live installation. A **confirmed** item follows directly
from a code path; a **risk** needs a failure-injection or hardware check; a **design
question** needs an operator decision. Each item names a practical resolution so
it can be taken on independently.

## Live playback and shutdown

1. **High, confirmed: RPC stop cannot interrupt Twinkly recovery.**
   `lyte/installation.py` constructs `TwinklyTrack` without its `stop_event`.
   `lyte/twinkly/realtime.py::recover_streaming_device` retries forever when that
   event is absent. The render thread can therefore remain inside recovery after
   `stop` sets `InstallationService._stop_requested`; it cannot reach the loop
   condition or blackout. Pass the service event to each track and cover stop
   during discovery, HTTP retries, and the retry delay.

2. **High, confirmed: a partially opened Twinkly output can miss cleanup.**
   `TwinklyOutput.open` prepares the device before creating its UDP socket, but
   `InstallationService.run` adds the output to `opened` only after `open` returns
   true. Socket creation failure, interruption, or another exception after
   realtime mode is entered leaves that output out of the shutdown list. Make
   opening exception-safe and close every output whose preparation began.

3. **High, confirmed: one cleanup failure prevents later cleanup.** The single
   `finally` in `InstallationService.run` closes recording, MIDI, Art-Net, pixel
   outputs, then reccy in sequence. If fixture-blackout rendering, one output's
   `close`, or another cleanup operation raises, subsequent outputs and the
   service are not closed. Isolate each shutdown action, record its failure, and
   always attempt the remaining blackouts and closes. Test multiple failing
   closers, including an interrupted stop.

4. **High, confirmed: live MIDI polling has no per-frame work limit.**
   `lyte/midi.py::input_messages` drains until `poll()` returns `None`, and
   `InstallationService._process_midi` consumes the entire iterator before
   rendering. A continuously arriving MIDI stream can starve frame delivery;
   recording every message also grows the pending journal list. Bound the number
   or time spent processing MIDI per delivery while preserving event order.

5. **High, confirmed: long stalls cause unbounded rendering catch-up.**
   `ActiveAnimation.render` advances every missed score tick in a `while` loop;
   the delivery scheduler also increments `next_frame` one interval at a time
   until current time. A long pause, high declared score rate, or slow effect can
   cause a prolonged burst of work and further lateness. Define a documented
   policy for catching up stateful scores under a large gap, and compute the next
   delivery mathematically rather than iterating missed send slots. Preserve
   timing where feasible and expose any deliberate skip.

6. **Medium, confirmed: a failed queued selection is silently lost.**
   `InstallationPlayback.render` clears `queued_name` before `select()` prepares
   the replacement. If preparation later raises, the live runner logs a render
   error and continues with the previous animation, but status no longer shows
   the rejected selection or why it failed. Keep the active look, report the
   rejected command in status, and acknowledge selection only when it is applied
   or explicitly report deferred validation failure to the operator.

7. **Medium, confirmed: startup assignment needs all devices in one scan.**
   `discover_assignments` discards the device list on each retry. If Dots and
   Strings answer on alternating discovery scans, both can be individually
   reachable yet the installation times out. Accumulate recently identified
   devices by stable identity during the startup deadline and expire stale
   observations deliberately. Also turn a discovery socket `OSError` into a
   bounded, visible startup failure/retry; that exception is not caught here.

8. **Medium, risk: output setup can outlast the configured startup bound by a
   large margin.** `startup_timeout` covers discovery and identification only.
   Each Twinkly `track.prepare()` then uses up to ten HTTP attempts with
   exponential delays and no shared deadline, one output after another. This is
   documented, but the setting's name invites a false expectation and RPC is
   not available until after discovery. Choose a separate, explicit setup
   timeout and make start/interrupt behavior observable.

9. **Medium, risk: shutdown time scales with the number of Twinkly outputs.**
   Each `TwinklyTrack.close` can spend up to three seconds trying to set off
   mode, and `InstallationService.run` closes tracks serially. Two strings can
   already add roughly six seconds; more outputs increase that bound. Decide
   what stop latency is acceptable for the first show and test an unreachable
   device during shutdown. This does not establish that UDP blackout packets
   reached the hardware.

10. **Medium, risk: WLED cannot recover a permanently unusable socket.**
    `WledOutput.send` lazily creates one `WledDdpOutput` and keeps it after any
    send failure. Transient send errors may clear on a later frame, but a socket
    that becomes invalid will be reused forever. Close and recreate it after
    socket-level failure, preserving the existing per-output isolation. DDP is
    unacknowledged, so status should continue to say delivery is unconfirmed.

11. **Medium, risk: a failed physical blackout can be hidden by process exit.**
    Twinkly shutdown records `UNKNOWN` if off-mode fails; WLED final black is
    best effort; Art-Net is unacknowledged. There is no final operator-facing
    aggregate of which outputs actually accepted the shutdown request, and
    closing the service removes live status. Log a concise per-output shutdown
    result and rehearse unreachable-device and gateway cases physically.

## Browser tools, recording, and exports

12. **High, confirmed: partial HTTP request bodies can hold local tools
    indefinitely.** The editor, panel, and rehearsal handlers call
    `rfile.read(Content-Length)` without a connection deadline. The panel and
    rehearsal use single-threaded `HTTPServer`, so one stalled local client
    blocks all status and controls. The editor uses `ThreadingHTTPServer`, but
    holds its session lock while reading and can create unbounded request
    threads. Set bounded per-connection timeouts and return clear timeout or
    busy responses; test a client that sends only part of its declared body.

13. **Medium, confirmed: editor GET races with mutations.**
    `lyte/authoring_http.py::do_GET` builds the catalogue and history without
    `session_lock`, while POST edits replace `session.animations`, `documents`,
    and history under that lock. A concurrent GET can show a mixed revision or
    fail while iterating changed documents. Take a consistent locked snapshot,
    then serialize it after releasing the lock.

14. **Medium, confirmed: panel reports service failures as user errors.**
    `lyte/panel.py::do_POST` catches both invalid input and `OSError` from
    `client.call` and responds 400 for either. An unavailable or timed-out lyte
    service should be reported as 503 (or a distinct connection error), so an
    operator does not revise a valid command while the control link is down.
    `rehearsal_http.py` similarly labels internal I/O errors as bad input.

15. **Medium, risk: editor preview work still has a substantial memory and
    latency peak.** The 10,000-frame/32 MiB check in
    `lyte/preview/document.py` limits raw pixels, but `AuthoringSession.preview`
    then stores base64 strings, serializes another JSON response, and may embed
    them into HTML. The global POST lock is held throughout rendering and
    catalogue rebuilding. Measure the near-limit peak and consider streaming,
    a smaller user-visible limit, or preflight/cancellation if it threatens the
    editor host. No claim of an actual out-of-memory failure is made here.

16. **Medium, confirmed: movie encoding has no hang timeout.**
    `lyte/render.py::render_animation` waits for `ffmpeg` without a deadline
    after writing frames. A stuck encoder keeps the CLI and temporary output
    indefinitely. Bound final wait and terminate/reap on timeout. Frame count
    is also controlled by unbounded width, height, duration, and score rate;
    preflight a realistic output budget before allocating huge frames or
    starting a multi-score batch.

17. **Medium, confirmed: WLED translation can leave a partial result.**
    `lyte/wled.py::translate_snapshot` writes each score before discovering a
    collision in a later filename or writing the manifest. `_write_json` also
    overwrites an existing snapshot, native preset export, or manifest without
    asking. Preflight all names and destinations, then publish a complete set
    atomically or fail without changing prior output. Distinguish the explicit
    overwrite policy for each action.

18. **Low, confirmed: replay accepts a valid end marker followed by garbage.**
    `ControlReplay.advance` stops reading at `{"kind":"end"}` and never checks
    that the file actually ends. A damaged or concatenated journal can be
    reported as complete. Validate EOF after the marker; also surface an
    incomplete journal at open time rather than only after its last playable
    frame if that improves the rehearsal workflow.

19. **Low, risk: a long editor session has unbounded history.** Every accepted
    edit in `lyte/authoring.py` stores full before/after TOML texts, with no
    history cap. Large scores edited repeatedly can consume much more memory
    than the current document. Measure typical session size; if material, cap
    undo history or store deltas with clear user-visible behavior.

## Configuration and operator-facing traps

20. **Medium, confirmed: the first-show Twinkly selector is fragile.**
    `patches/showco-installation.toml` matches Dots by substring and assigns
    Strings using an empty selector. This is valid only while exactly one
    unclaimed device remains; adding a third string or another matching Dots
    device makes startup ambiguous. Record a distinguishing observed gestalt
    field for Strings and preflight the actual two controllers before the show.
    The selector API uses substring rather than exact identity, which should be
    clearly signalled to an operator.

21. **Medium, confirmed: README describes an older runtime.** Its opening and
    installation sections say WLED and DMX are separate primitives and that
    installation playback does not combine them. Current
    `lyte/installation.py` and `lyte/installation_dmx.py` do combine them.
    Update the first-screen description and installation examples, because
    this is likely the first source a new operator reads.

22. **Low, design question: `lyte installation` accepts irrelevant options.**
    `InstallationCommandConfig` exposes `duration`, `record_input`, and a config
    path for every action. `record_input` is explicitly rejected outside `run`,
    but `duration` is silently ignored for `install`, `stop`, `status`, and other
    actions; `status` also ignores its config path. Make invalid combinations
    errors or give actions separate command types so help shows only applicable
    arguments.

23. **Low, design question: several public names obscure their scope.** A
    `StringStatus` also describes WLED outputs, `outputs` in an animation binds
    pixel score outputs to physical strings, and `master_level`, fades, and
    tests affect pixels but do not interpolate or dim DMX fixture channels.
    The `lyte wled` command imports/exports presets, whereas `[wled]` in an
    installation streams DDP. Explain these boundaries in help and panel labels
    before considering API renames. MIDI `program_change` advances to the next
    look while ignoring its program number; this is documented but is easy to
    mistake for direct program selection.

24. **Low, design question: physical stop semantics depend on authored fixture
    data.** `FixturePlayback` requires a profile with `stop.kind = "blackout"`
    and applies each fixture's `blackout` values, but software validation cannot
    prove that those values actually cut a laser or put a fixture in a safe
    state. Keep fixture-specific modes explicit and make a physical stop check
    part of show preparation. Do not replace the laser's centred geometry with
    zeroed channels merely because that looks like a generic blackout.

## Project and test structure

25. **Medium, maintenance risk: several source and test files now span multiple
    concerns.** `lyte/authoring.py` (861 lines) combines session state,
    editing, library reconstruction, and catalogue generation;
    `lyte/authoring_template.py` (939 lines) combines HTML, CSS, and JavaScript.
    `lyte/fps_test.py` (830 lines) contains multiple interactive diagnostics.
    `tests/test_installation.py` (902 lines) spans config, discovery, timing,
    service lifecycle, and MIDI. Split by cohesive behavior when changing these
    areas, keeping one implementation and the existing public paths. There is
    no compelling tiny-file inlining candidate: the short effect modules are
    named public/registry entries, and inlining them would move those names.

26. **Low, limited overlap with reccy: retry scheduling is implemented twice.**
    `lyte/retry.py` owns attempt timing, delay, backoff, deadlines, and
    cancellation while `reccy/runtime/retry.py` already provides
    `RetryPolicy`/`RetrySchedule` for those timing decisions. lyte's helper also
    executes operations and logs failures, so it is not a duplicate daemon or
    a drop-in replacement. If retry behavior changes, reuse reccy's schedule
    and retain lyte-specific execution/logging only where needed.

27. **Medium, test gap: failure boundaries above are mostly not exercised.**
    The suite has useful focused coverage for mixed WLED failure, status-write
    failure, render continuation, retry cancellation, and recording failure.
    It does not cover installation RPC stop during actual recovery, partial
    Twinkly open, one closer failing before the others, continuous MIDI input,
    slow HTTP bodies, editor GET/POST concurrency, or hung `ffmpeg`. Add narrow
    deterministic tests when fixing the corresponding paths. Keep physical
    delivery/blackout checks separate; UDP send success is not light output.

28. **Low, test organization: large suites obscure ownership, but no clear
    broad duplicate-test removal is justified.** `tests/test_installation.py`
    and `tests/test_authoring.py` exceed 800 lines; the first mixes parser and
    runtime cases, while the latter mixes editor features. Separate them by
    behavior as touched. `tests/test_cli_help.py` already uses reccy's shared
    help regression fixture, and the animation tests cover distinct effects;
    deleting them for size alone would lose useful protection.

## Additional work beyond the prompt

None.

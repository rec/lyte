# Live Performance Failure Audit

## Scope

This audit covers the current foreground `LyteMidiDaemon`, its MIDI input loop,
`TwinklyTrack` realtime output path, HTTP/UDP transport, and Reccy local RPC.
It is based on source and unit-test inspection only. No physical device or
network test was run for this document.

The objective is not merely to keep the daemon process alive. During a show it
must remain controllable, tell the operator what output is actually known to be
working, resume safely when hardware returns, and avoid leaving a stale bright
frame on the lights.

## Current Behavior

- A failed local UDP send starts `TwinklyTrack` recovery. Recovery repeatedly
  discovers, authenticates, and restores realtime mode until it succeeds.
- A missing MIDI port is retried, and an `OSError` while polling a port causes
  it to be closed and reopened.
- Cleanup tries to switch the Twinkly to off mode whenever an existing track
  exits its playback loop.
- Reccy local RPC can report status, request stop or blackout, and queue a
  named patch selection.

These mechanisms are useful, but a live outage can currently make the only
frame loop unavailable for an unbounded period. Several failures are invisible
or are reported as healthy streaming.

## Critical Problems

### 1. UDP success is not evidence that the lights received a frame

`send_frame_v3()` uses connectionless UDP. `sendmsg()` commonly succeeds while
the Twinkly is unplugged, powered off, out of Wi-Fi range, or has stopped
accepting realtime frames. `TwinklyTrack.stream_frames()` recovers only after a
local send error or missing token. It can therefore continue to report
`streaming` indefinitely while the device shows the last frame or nothing.

**Required change**

1. Define an output-health policy for realtime playback. It must have a bounded
   HTTP health probe or another device acknowledgement while streaming.
2. Mark output `unknown` or `recovering` after a configurable number of failed
   probes. Do not claim `streaming` merely because local UDP accepted packets.
3. Reauthenticate and restore realtime mode after a failed probe, then resume
   frames only after the probe succeeds.
4. Publish the health state, current host, last successful probe, and recovery
   attempt count through `LyteMidiStatus` and Reccy events.

**Tests**

- A UDP sender that reports bytes sent while the health probe fails enters
  recovery.
- Successful recovery returns status to `streaming` and preserves patch and
  current MIDI performance.
- An unreachable device is visible as `recovering` or `unknown`, never
  `streaming`.

**Physical verification**

- Power off the Twinkly while streaming, then restore power without restarting
  Lyte. Confirm that status changes promptly, recovery occurs, and the selected
  patch resumes.

### 2. Per-frame retries can block the show for minutes

The daemon uses the general retry policy for every UDP frame. With the current
configuration of ten attempts, 0.5-second delay, and 2x backoff, one failed
frame can sleep for about 255.5 seconds before recovery starts. HTTP requests
also use the five-second connection timeout for every retry.

While this happens, no frame is rendered, no MIDI is consumed, and no queued
stop or patch-selection request is handled.

**Required change**

1. Separate realtime-frame failure handling from setup and cleanup retries.
   A realtime send should fail promptly, without an exponential retry loop.
2. Give startup, recovery, and blackout explicit bounded retry/deadline
   policies. Their elapsed time and next retry time must be observable.
3. Make waits interruptible by a shutdown request. A stop must never wait for
   the full network retry schedule.
4. Revisit the five-second HTTP timeout for live recovery. Use a short,
   configured operational timeout with a separate configuration value for
   non-live diagnostics if needed.

**Tests**

- A failed frame enters recovery after one send attempt.
- Stop during an HTTP timeout, retry delay, discovery attempt, and recovery
  loop exits within the chosen shutdown bound.
- Retry schedules are capped and do not grow without an operator-visible
  deadline.

### 3. MIDI loss freezes output and blocks shutdown

`process_messages()` opens the MIDI port in a `while port is None` loop. On
startup or after a disconnect it sleeps until the port returns. Because this
runs inside `TwinklyTrack.stream_frames()` before rendering each frame, the
lights retain their last frame and all output stops while MIDI is absent.
Neither a queued RPC stop nor a patch selection is examined inside that loop.

On MIDI disconnect, the active note and patch state also remain active. If the
port returns, the old note can continue producing light even though the
instrument has been silent.

**Required change**

1. Make MIDI reconnection non-blocking relative to output. Poll for a port at a
   bounded interval while continuing the frame loop.
2. Decide and document the loss-of-controller safety policy. The recommended
   first policy is to end the active note and render black when a MIDI input is
   confirmed disconnected, while leaving the selected patch ready for the next
   note after reconnection.
3. Check the shutdown signal before and during every port-open wait.
4. Record `midi_connected`, the selected input name, and the most recent MIDI
   error in daemon status.

**Tests**

- Missing MIDI input does not prevent black frames or output health checks.
- MIDI disconnect ends the active note, then reconnection accepts a new note.
- Stop while waiting for a MIDI port exits promptly.
- A port whose `close()` raises does not prevent Twinkly cleanup.

**Physical verification**

- Unplug and replug the wind controller during an active note. Confirm a safe
  black state, recovery without restarting the service, and normal input after
  replugging.

## Important Problems

### 4. Startup failures leave no controllable daemon

Twinkly discovery, LED-count reading, and track construction happen before
`LyteMidiDaemon.start()`. A discovery parse error, socket error, or failed
startup returns or raises before Reccy status and RPC are available. With an
unbounded discovery timeout, there is no local stop command during initial
connection.

**Required change**

1. Start Reccy and publish a `connecting` status before device discovery.
2. Keep startup connection attempts in the daemon lifecycle, not ahead of it.
3. Make startup retry and shutdown cancellation use the same policy as recovery.
4. Catch expected discovery and transport failures at this boundary, publish the
   error, and continue retrying or exit according to configured policy.

### 5. Device identity is not preserved during rediscovery

Recovery accepts the first discovered Twinkly with the expected LED count.
Another device with the same count can be selected after a Wi-Fi change.

**Required change**

1. Persist the initially verified Twinkly MAC or device ID as the expected
   identity for the run.
2. Require that identity during recovery. A mismatch remains `recovering` and
   is reported to the operator rather than becoming output to another device.
3. Keep an explicit escape hatch only when intentionally configured for device
   replacement.

### 6. Cleanup is best-effort but can be slow and is not status-visible

`TwinklyTrack.close()` calls the same retrying HTTP off operation. During an
outage it can block for the full retry schedule, and a failed blackout only
changes an in-memory connection state. The daemon status does not report the
connection state or failed blackout. Failures before track construction have no
blackout attempt at all.

**Required change**

1. Use a short bounded blackout policy during shutdown.
2. Publish `blacked_out` only after the device confirms off mode; publish
   `unknown` with the reason otherwise.
3. Ensure every process-exit path has a clear rule for whether a Twinkly client
   was successfully prepared and needs cleanup.
4. Test `SIGTERM` at startup, during normal stream, and during recovery.

### 7. Render and patch exceptions terminate the daemon

MIDI message handling, patch construction, patch rendering, physical-map
encoding, and frame validation can raise. The broad outer `finally` attempts
cleanup, but the exception still exits the service and relies on the service
manager to restart it. No Reccy error is published, and the recovery context is
lost.

**Required change**

1. Define a narrow failure boundary around a single MIDI message and a single
   render. Record the error, render a safe black frame where possible, and keep
   the daemon alive when the fault is input-specific.
2. Treat an invalid configured patch or repeated render failure as a distinct
   fatal configuration error with clear status and bounded restart behavior.
3. Add error counters and the current patch name to status so a restart loop is
   diagnosable.

### 8. The daemon's reported state is too coarse

`LyteMidiStatus.state` is set to `streaming` once and remains so during MIDI
loss, failed UDP recovery, and failed blackout. Network and MIDI errors are
only logged; they are not sent through `publish_error()` and do not appear in
persisted status or events.

**Required change**

Extend the status model with at least:

- lifecycle state: `connecting`, `streaming`, `recovering`, `stopping`,
  `stopped`, or `unknown`;
- output host and verified device identity;
- output health and last confirmed contact;
- MIDI connection state and last input error;
- selected patch, active-note summary, and recovery count;
- last failure message and timestamp.

Use state changes, not every frame, to publish status and events.

## MIDI Message Handling

Mido presents the application with complete `mido.Message` instances; it does
not expose raw serial bytes here. A transport-level partial MIDI message should
normally be retained by the backend until complete, rather than passed to
`Patch.receive()`. This needs physical confirmation for the selected MIDI
backend.

However, Lyte currently assumes every yielded object is a valid Mido message.
An unexpected backend exception while iterating is caught only when it is an
`OSError`; malformed objects or validation errors can terminate the daemon.
There is no input-flood bound, and draining all available messages before every
frame can make rendering late under a burst.

**Required change**

1. Confirm the actual Mido backend's partial-message and disconnect behavior
   with a small hardware test.
2. Catch documented backend parsing and device errors at the MIDI boundary,
   log and publish them, then reconnect.
3. Apply a per-frame message budget while retaining arrival order. Carry excess
   messages to later frames rather than allowing unbounded MIDI draining to
   starve output.
4. Define handling for an impossible message: discard it, report it once or
   rate-limit reports, and keep output alive.

## RPC Robustness and Concurrency

`LyteMidiDaemon.rpc_response()` protects its private request fields with a
lock, and patch selection is applied by the frame loop. That avoids concurrent
mutation of a patch while it renders. There are still important semantic and
transport gaps:

- `select_patch` returns `ok` when queued, not when applied. Concurrent
  selections can overwrite each other, so a caller can receive success for a
  patch that is never rendered.
- A request arriving while MIDI reopening or Twinkly recovery is blocked is not
  acted on until that blocking operation returns.
- The status request can report the previous patch immediately after a queued
  selection.
- Reccy's RPC server parses incoming messages in per-connection threads without
  catching validation or handler errors. Malformed JSON, an invalid RPC model,
  or an exception from the handler closes that request without a structured
  error. A client that connects and never sends a hello can hold a daemon thread
  indefinitely; enough local connections can exhaust threads.

**Required change**

1. Define RPC semantics explicitly: queued versus applied selection, selection
   generation number, and the stop/blackout priority rule.
2. Add a cancellation signal checked by all blocking runtime operations.
3. In Reccy, convert malformed requests and handler failures into bounded,
   structured `ipc.Error` replies, with connection and handshake timeouts.
4. Add request size and concurrent-request limits appropriate to local control.
5. Test malformed JSON, a wrong message type, missing command, invalid
   `select_patch` parameters, concurrent selections, and stop during recovery.

## Network and Device Input Validation

- `discover()` can raise socket, discovery-format, Unicode decoding, and address
  errors. `discover_host()` does not convert these into a retryable discovery
  failure.
- HTTP request code converts `OSError` into `ProtocolError`, but JSON decoding
  can also raise `UnicodeDecodeError`, which is not caught. Application response
  values are only lightly validated.
- Realtime-frame packet generation validates the token and frame shape, but a
  render exception can still end playback as noted above.
- A DNS host, router outage, or total loss of the Pi's network can therefore
  either block repeated timeouts or end the daemon, depending on where it occurs.

**Required change**

Normalize expected device input failures into a small set of retryable errors at
the discovery, HTTP, and realtime boundaries. Preserve the original error in
status/logging, but do not let malformed network input escape the live runtime.

## Test Gaps

Existing tests cover individual retry calls, basic discovery packet parsing,
local UDP send failure, successful recovery, MIDI port reopen after an
`OSError`, and normal cleanup. They do not cover:

- unreachable-but-UDP-sendable lights;
- bounded frame-send, HTTP, discovery, recovery, and shutdown time;
- Twinkly power loss and restoration across the daemon loop;
- MIDI loss while a note is active, while a reconnect is pending, or while a
  stop request arrives;
- malformed or flooded MIDI input;
- discovery socket and malformed-response failures through the daemon;
- RPC wire-level malformed requests, handshake stalls, concurrent requests, or
  cancellation during recovery;
- status/error/event output during each outage;
- wrong-device recovery with the same LED count;
- cleanup failures while the network is unavailable.

## Implementation Order

1. Add a cancellable runtime-control signal and a status model that accurately
   reports connection and MIDI state. Start Reccy before device connection.
2. Separate quick realtime-send failure from bounded startup, recovery, and
   blackout policies. Make all waits interruptible.
3. Refactor the frame loop so MIDI reconnection never blocks rendering or
   output-health monitoring. Define and implement MIDI-disconnect blackout.
4. Add output health probing and verified device identity during recovery.
5. Add narrow fault boundaries for MIDI input, rendering, discovery, and device
   responses, with Reccy error publication.
6. Harden Reccy RPC parsing, timeouts, and cancellation. This is cross-project
   work and belongs in Reccy, with Lyte integration tests after it lands.
7. Add deterministic fake-clock and fake-device tests for every failure path,
   then perform the physical verification listed above one failure at a time.

## Additional Work Beyond the Prompt

None.

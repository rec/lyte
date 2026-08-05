# XLED Feature Plan

The xled documentation describes a much larger Twinkly HTTP API surface than
Lyte currently models. Lyte should add that surface deliberately, with safe
read-only discovery first and mutating operations behind explicit APIs.

Source: [xled RESTful API reference](https://xled-docs.readthedocs.io/en/latest/rest_api.html)

## Current Lyte Coverage

Lyte currently supports only a narrow subset of the documented XLED API:

- login and verify through `LyteClient.authenticate()`
- unauthenticated `gestalt` through `read_gestalt()`
- copying MAC and LED count from `gestalt`
- `POST /xled/v1/led/mode` for realtime mode and off mode only
- Twinkly realtime UDP frame sending

Lyte does not currently expose structured device details, brightness,
saturation, layout, movie management, playlists, WiFi state, MQTT, mic/music
features, firmware/status endpoints, HTTP realtime frames, or most mode/color
operations.

## General Approach

Add XLED support in layers:

1. Add low-level client methods for generic `GET`, `POST`, `DELETE`, and binary
   POST bodies where needed.
2. Add small typed models only for stable, useful responses.
3. Keep raw response access available for diagnostics where fields vary by
   firmware family.
4. Implement read-only endpoints before mutating endpoints.
5. Require explicit user commands for destructive or network-changing actions.
6. Do not run device calls in tests; unit-test request paths, payloads, response
   parsing, and validation.

The XLED API is reverse-engineered and firmware-dependent. The plan should treat
404 "Resource not found" as a normal capability result, not necessarily a hard
failure.

## Phase 1: Client Foundation

Add client features needed by the documented endpoints:

- `delete(path)`.
- binary `post_bytes(path, payload, content_type)`.
- optional unauthenticated requests for `fw/version` and `status`.
- capability-friendly errors for 404 responses.
- a shared request-label strategy for retry wrappers.

Keep the existing JSON `get()` and `post()` methods intact.

## Phase 2: Device State And Diagnostics

Implement read-only device state first. These are low-risk and useful for
debugging real devices:

- `GET /xled/v1/gestalt`: structured `TwinklyDeviceInfo` wrapper around the raw
  gestalt response, preserving unknown fields.
- `GET /xled/v1/device_name`.
- `GET /xled/v1/fw/version`.
- `GET /xled/v1/status`.
- `POST /xled/v1/echo` for authenticated connectivity testing.
- `GET /xled/v1/summary`.

Update diagnostics to print:

- firmware family and version
- LED profile, bytes per LED, frame rate, measured frame rate
- app brightness and saturation settings
- current mode
- layout source and coordinate count
- movie capacity and stored movie count

## Phase 3: Brightness And Saturation

Implement the app-level output filters that directly affected recent
calibration:

- `GET /xled/v1/led/out/brightness`.
- `POST /xled/v1/led/out/brightness`.
- `GET /xled/v1/led/out/saturation`.
- `POST /xled/v1/led/out/saturation`.

Represent both as the same small model:

```text
mode: enabled | disabled
type: A | R for set requests
value: percent
```

Add CLI support for:

```text
lyte brightness get
lyte brightness set 100
lyte saturation get
lyte saturation set 100
```

Default realtime test commands should eventually warn when brightness is enabled
below 100 percent, because it changes the effective byte-to-light mapping.

Do not silently force brightness to 100 in animation commands. Make that an
explicit option after the getter/setter exists.

## Phase 4: LED Modes And Static Color

Lyte currently posts only `rt` and `off`. Add the rest of the documented mode
surface:

- `GET /xled/v1/led/mode`.
- `POST /xled/v1/led/mode` for `off`, `color`, `demo`, `effect`, `movie`,
  `playlist`, and `rt`.
- `GET /xled/v1/led/color`.
- `POST /xled/v1/led/color` using RGB or HSV payloads.
- `GET /xled/v1/led/effects`.
- `GET /xled/v1/led/effects/current`.
- `POST /xled/v1/led/effects/current`.

Keep static color separate from realtime animation. It is a device mode, not an
animation frame path.

## Phase 5: Layout And Device Configuration

Implement layout as a first-class model because it can improve preview and
future physical mapping:

- `GET /xled/v1/led/layout/full`.
- `POST /xled/v1/led/layout/full`.
- `DELETE /xled/v1/led/layout/full`.

Represent coordinates as `x`, `y`, `z` floats plus layout metadata:

- `source`: `linear`, `2d`, or `3d`
- `synthesized`
- `uuid`
- `aspectXY`
- `aspectXZ`

Also implement string configuration:

- `GET /xled/v1/led/config`.
- `POST /xled/v1/led/config`.

Treat layout upload/delete and LED string config as explicit advanced commands.
They modify device state and should not be part of ordinary animation playback.

## Phase 6: Timers

Implement:

- `GET /xled/v1/timer`.
- `POST /xled/v1/timer`.

Model times as seconds after midnight, preserving `-1` for disabled on/off
times. This belongs in diagnostics and device management, not the show runner.

## Phase 7: Movies And Playlists

Add movie management after realtime and float-frame work is stable:

- legacy full movie upload: `POST /xled/v1/led/movie/full`
- movie config: `GET /xled/v1/led/movie/config`
- set movie config: `POST /xled/v1/led/movie/config`
- list movies: `GET /xled/v1/movies`
- delete all movies: `DELETE /xled/v1/movies`
- create movie entry: `POST /xled/v1/movies/new`
- upload movie body: `POST /xled/v1/movies/full`
- get current movie: `GET /xled/v1/led/movies/current`
- set current movie: `POST /xled/v1/led/movies/current`
- get playlist: `GET /xled/v1/playlist`
- create playlist: `POST /xled/v1/playlist`
- delete playlist: `DELETE /xled/v1/playlist`
- get current playlist entry: `GET /xled/v1/playlist/current`
- set current playlist entry: `POST /xled/v1/led/playlist/current`

Movie upload needs binary body support and channel-layout-aware frame encoding.
Do not implement it before the floating-point/channel-frame migration has a
clear device encoder.

Destructive movie and playlist operations should require explicit CLI commands
whose names say what they delete.

## Phase 8: Network Status And WiFi Scan

Implement read-only network support:

- `GET /xled/v1/network/scan`
- `GET /xled/v1/network/scan_results`
- `GET /xled/v1/network/status`

Defer mutating network status until there is a real need:

- `POST /xled/v1/network/status`

Changing WiFi can strand the device. It should require a separate command, a
clear warning, and probably manual confirmation if Lyte ever exposes it.

## Phase 9: MQTT, Mic, And Music

Implement read-only endpoints first:

- `GET /xled/v1/mqtt/config`
- `GET /xled/v1/mic/config`
- `GET /xled/v1/mic/sample`
- `GET /xled/v1/music/drivers`
- `GET /xled/v1/music/drivers/sets`
- `GET /xled/v1/music/drivers/sets/current`

Defer `POST /xled/v1/mqtt/config` until Lyte has a reason to manage Twinkly
cloud or broker configuration.

Mic and music endpoints are probably diagnostic or future control-signal inputs.
They should not be mixed into animation rendering.

## Phase 10: HTTP Realtime Frame

Lyte currently uses the realtime UDP protocol. XLED also documents:

- `POST /xled/v1/led/rt/frame`

Add this only as an alternate transport after the frame encoder boundary is
clean. It may be useful for devices or network conditions where UDP realtime is
awkward, but it should not replace UDP without measurement.

## Phase 11: Explicitly Dangerous Or Low-Priority Endpoints

Do not implement these until Tom explicitly asks:

- `POST /xled/v1/fw/update`
- `POST /xled/v1/fw/0/update`
- `POST /xled/v1/fw/1/update`
- `POST /xled/v1/led/driver_params`
- `GET /xled/v1/led/reset`
- `GET /xled/v1/led/reset2`
- `POST /xled/v1/logout`

Reasons:

- firmware update can brick a device
- driver timing parameters can break LED output
- reset endpoints have unclear behavior
- logout is documented as probably invalidating tokens and "doesn't work"

These can still be represented in a capability inventory as unsupported.

## Capability Inventory

Add a command or diagnostic section that reports which endpoints are available
on the current device. The xled docs list firmware-version and family
differences, and devices may return 404 for missing endpoints.

The capability probe should:

- query read-only endpoints only
- record success, 401, 404, and application error codes
- never mutate device state
- include firmware family/version and product code in the report

## CLI Shape

Keep CLI additions narrow and operational:

```text
lyte diagnostic
lyte brightness get|set
lyte saturation get|set
lyte mode get|set
lyte color get|set
lyte layout get|export|upload|delete
lyte movie list|current|set-current|delete-all|upload
lyte playlist list|create|current|set-current|delete
lyte network status|scan|scan-results
lyte xled capabilities
```

Do not add every command at once. Implement them as feature groups reach tests.

## Test Strategy

Unit tests should cover:

- request method/path/payload for every endpoint wrapper
- response parsing for documented examples
- validation of value ranges and enum values
- 404 capability handling
- binary upload request construction without sending real data

Do not write tests that require real Twinkly hardware. Hardware validation
should remain manual and explicit.

## Implementation Order

1. Client foundation: `DELETE`, binary POST, capability-aware 404 handling.
2. Read-only diagnostics: device name, firmware version, status, summary,
   mode, brightness, saturation.
3. Brightness and saturation get/set CLI.
4. Mode and static color get/set.
5. Layout get/export, then upload/delete later.
6. Movie and playlist read-only listing/current state.
7. Movie upload and playlist creation after channel-frame encoding is stable.
8. Network read-only status and scan.
9. MQTT/mic/music read-only diagnostics.
10. HTTP realtime frame as an alternate transport.
11. Dangerous endpoints only on explicit request.

## Additional Work Beyond the Prompt

None.

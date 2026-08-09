# Split `tests/test_lyte.py`

## Goal

Replace the single `tests/test_lyte.py` module with focused test modules whose
names match the production subsystem under test. Preserve every existing test
and test name unless a move reveals an actual duplicate. This is a structural
change, not an opportunity to change production behavior or broaden coverage.

The completed layout should let a failure name its subsystem without opening a
four-thousand-line file, while retaining the present `tests/test_hamiltonian.py`
optional physical-style check.

## Principles

- Move tests by the module or public behavior they exercise, not by their
  current `unittest.TestCase` class name alone.
- Keep a test that exercises an observable end-to-end command path separate
  from tests of the individual function it dispatches to.
- Keep fakes next to the subsystem that uses them unless three or more modules
  need the same fake. Only then create `tests/conftest.py` or a small support
  module.
- Do not create `tests/__init__.py` merely to share helpers.
- Do not rename tests just to match a new filename. Rename only a test whose
  current name becomes inaccurate after moving.
- Do not combine the existing optional Hamiltonian check with normal unit
  tests. It remains opt-in under its current environment switch.

## Target Layout

### Core, show, and patch graph

| New file | Move from `tests/test_lyte.py` | Production scope |
| --- | --- | --- |
| `tests/test_animation.py` | float-frame validation and conversion, core `Animation`, `SegmentAnimation` | `lyte/animation.py` |
| `tests/test_show.py` | `ShowFileTests` | `lyte/show.py` |
| `tests/test_midi.py` | `MidiTests` | `lyte/midi.py` |
| `tests/test_patches.py` | `PatchLibraryTests` | `lyte/patches.py`, `patches/wearable-breath.toml` |
| `tests/test_retry.py` | `RetryTests`, `RetryableTestError` | `lyte/retry.py` |
| `tests/test_logging.py` | `LoggingTests` | `lyte/logging.py` |

`render()` and `initial_state()` should move only if their destination modules
actually use them. If only one test file needs either helper after migration,
make it local to that file instead of creating shared test infrastructure.

### Animation libraries and preview

| New file | Move from `tests/test_lyte.py` | Production scope |
| --- | --- | --- |
| `tests/test_animations_christmas.py` | `ChristmasAnimationTests`, `HamiltonianTests`, `RandomWalkTests`, `HamiltonianAnimationTests` | `lyte/animations/christmas/` |
| `tests/test_animations_bibliopixel.py` | `BiblioPixelTests` | `lyte/animations/bibliopixel/` |
| `tests/test_preview.py` | `PreviewTests` | `lyte/preview/document.py`, `layout.py`, `template.py` |
| `tests/test_preview_command.py` | `PreviewCommandTests` | `lyte/preview/command.py`, `config.py` |
| `tests/test_fps_test.py` | frame-rate, temporal-dither, black-floor, verification, keyboard-reading, and reporting tests currently in `FpsTestTests` | `lyte/fps_test.py` |
| `tests/test_animate.py` | `AnimateTests` | `lyte/animate/` |

Move tests for `gradient_frame()` and `blend_frames()` with the module that
defines them, even though they currently appear among CLI and FPS tests.

### Twinkly protocol and commands

| New file | Move from `tests/test_lyte.py` | Production scope |
| --- | --- | --- |
| `tests/test_twinkly_authentication.py` | `CryptoTests` | `lyte/twinkly/authentication.py` |
| `tests/test_twinkly_discovery.py` | `DiscoveryTests` | `lyte/twinkly/discovery.py` |
| `tests/test_twinkly_frame.py` | packet, fragment, payload, socket-send, and token tests currently in `RealtimeTests` | `lyte/twinkly/frame.py` |
| `tests/test_twinkly_client.py` | `FakeHttpResponse`, `FakeHttpConnection`, `ClientTests` | `lyte/twinkly/client.py` |
| `tests/test_twinkly_session.py` | `SessionTests`, `RuntimeTests` | `lyte/twinkly/session.py`, `realtime.py` |
| `tests/test_twinkly_diagnostic.py` | `PackageDiagnosticTests`, `DiagnosticTests` | `lyte/twinkly/diagnostic.py`, `realtime_diagnostic.py` |
| `tests/test_twinkly_controls.py` | `TwinklyControlTests` | Twinkly output, mode, layout, timer, media, networking, and inputs command modules |

Keep the HTTP fake in `tests/test_twinkly_client.py` until another Twinkly test
module genuinely needs it. If that happens, extract the fake unchanged to a
single `tests/conftest.py` fixture or helper and update only its direct users.

### CLI dispatch

Create `tests/test_cli.py` for the `cli.main()` dispatch tests currently spread
through `FpsTestTests`, including animate, preview, patch, show, diagnostics,
test utilities, and each Twinkly endpoint command. These are command-selection
tests, not FPS or protocol tests.

The test should continue to use the public command-line arguments and assert
the resulting command config. It should not duplicate detailed behavior tests
that belong in `test_animate.py`, `test_preview_command.py`, or a Twinkly
command module.

## Migration Order

1. Create the destination test files with the imports required by their own
   tests. Move the core, show, MIDI, patch, retry, and logging tests first.
   Keep their helpers local. Run the whole suite and commit the batch.
2. Move Christmas, BiblioPixel, preview, FPS utility, preview-command, and
   animate tests. Move each helper to the file that owns the production function
   it exercises. Run the whole suite and commit the batch.
3. Move Twinkly authentication, discovery, frame, client, session, diagnostic,
   and controls tests. Keep the fake HTTP connection with client tests unless
   reuse proves a shared helper is warranted. Run the whole suite and commit
   the batch.
4. Move every CLI dispatch test into `tests/test_cli.py`. Remove these tests
   from the subsystem files once their command parsing assertions pass in the
   new location. Run the whole suite and commit the batch.
5. Remove `tests/test_lyte.py` only after `rg -n 'test_lyte' tests pyproject.toml`
   finds no remaining references and pytest collection reports the same number
   of normal tests as before the split, apart from intentional duplicate removal
   documented in the commit.

Each batch should run:

```sh
uv run pytest
uv run ruff check --fix --select B,E,F,I lyte tests
uv run ruff format lyte tests
uv run ty check lyte
version=$(tr -d . < .python-version)
find lyte tests -name '*.py' -print0 | xargs -0 uv run pyupgrade --py${version}-plus
```

## Duplicate Review

Do not delete tests preemptively. Review possible duplication only after the
move makes it visible:

- CLI dispatch tests that only repeat another dispatch test with different
  literal arguments should be consolidated into a parameterized table only when
  the observable command configuration remains equally clear.
- Protocol command tests that share authentication and cleanup setup are not
  duplicates merely because they use the same mocks. They verify different
  endpoint calls and should remain separate.
- Frame conversion, preview encoding, and realtime packet tests cover different
  boundaries and should remain independent.

Any deletion should state which existing test provides the retained coverage.

## Completion Criteria

- `tests/test_lyte.py` no longer exists.
- Every moved test has one clear production owner.
- The normal pytest collection count is unchanged unless a documented duplicate
  was intentionally removed.
- The optional Hamiltonian test remains skipped by default and runnable with
  its existing opt-in setting.
- No production imports, public API, or runtime behavior changes as part of the
  split.

## Additional work beyond the prompt

None.

# Parallel unit tests

## Goal

Reduce local and CI feedback time by running independent unit tests in parallel
without changing what the suite proves or making failures dependent on worker
order. `uv run pytest -q` remains the authoritative serial command until the
parallel command has been measured and adopted.

## Current constraints

Most tests are suitable for separate pytest workers: they use `tmp_path`,
`monkeypatch`, `unittest.mock`, or in-memory fakes. They must remain independent
of real Twinkly, WLED, Art-Net, MIDI, browser, and audio devices.

Treat these as serial until an audit proves otherwise:

- `tests/test_cli_help.py` when regenerating its checked-in fixture with
  `--force-regen`; concurrent writers could corrupt or make a misleading diff.
- Any test that writes below the repository, a fixed home/state path, a fixed
  TCP/UDP port, or a shared snapshot path. Move its output into `tmp_path` or
  give it a distinct worker-specific path before enabling it in parallel.
- Tests which change process-global state, such as environment variables,
  current directory, module-level clocks, or logging handlers, unless their
  fixture restores that state reliably.

Normal snapshot comparison through `pytest-regressions` is safe once each test
has its own fixture directory; regeneration remains a deliberate serial action.

## Milestone 1: establish a baseline and audit isolation

1. Record wall-clock duration and test count for serial `uv run pytest -q` on a
   representative development machine and CI runner.
2. Run collection twice and compare node IDs. Identify every test using fixed
   paths, ports, repository writes, `Path.home()`, `os.chdir`, global monkeypatch
   targets, or fixture regeneration.
3. Add focused regression tests for each repaired test boundary. A repair must
   use a pytest-provided temporary path or a worker-specific resource, never a
   time-based filename or retry loop.
4. Repeat serial runs enough times to rule out an existing flaky test before
   attributing failures to parallelism.

Complete when every mutable external resource is either per-test or explicitly
classified as serial.

## Milestone 2: add explicit parallel execution

1. Add `pytest-xdist` as a development dependency in its own dependency commit.
2. Add a documented command, initially `uv run pytest -q -n auto`, for the
   worker-safe suite. Do not make it pytest's implicit default yet.
3. Keep fixture regeneration separate:

   ```bash
   uv run pytest tests/test_cli_help.py --force-regen -q
   uv run pytest -q -n auto
   ```

4. If any tests remain intentionally serial, mark them with a locally defined
   `serial` marker in `pyproject.toml` and run them after the parallel group:

   ```bash
   uv run pytest -q -n auto -m 'not serial'
   uv run pytest -q -m serial
   ```

   Prefer eliminating the marker by isolating the resource. Do not split the
   suite by filename merely to hide a shared-state problem.

5. Add concise documentation beside the existing test instructions explaining
   normal parallel runs, serial fixture regeneration, and the reason both paths
   exist.

Complete when a clean checkout passes serially and in parallel with the same
test count and no test requires a physical device.

## Milestone 3: validate stability and choose the default

1. Run the parallel command repeatedly on a clean checkout, including at least
   one run with a different worker count. Compare failures, test count, and
   regression fixture output with the serial baseline.
2. Measure runtime for `-n auto`, a modest fixed worker count, and serial mode.
   Choose the fastest stable setting for CI; cap workers if NumPy rendering or
   movie fixtures contend for CPU or memory.
3. In CI, use the chosen parallel command for ordinary verification and retain
   one serial run for help-fixture regeneration or any remaining serial marker.
   Preserve failure output grouped by test so a worker failure is diagnosable.
4. Only after these checks pass, make parallel execution the documented default.
   Keep a clearly named serial command for debugging and for validating changes
   to the test harness itself.

## Risks and non-goals

- Parallelism cannot make hardware readiness tests valid; the suite continues
  to use mocks and rehearsal paths.
- Do not add retries, random resource names, shared daemons, or test-order
  dependencies to make a race appear to pass.
- Do not parallelize CLI-help fixture writes or snapshot updates. They are
  source-generation actions, not ordinary assertions.
- This plan does not change application concurrency or runtime service limits.

## Additional work beyond the prompt

None.

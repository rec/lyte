# Split `lyte.animate`

`lyte/animate.py` is now the package home for the old animation runner, but it is
too broad for long-term maintenance. It mixes CLI-facing configuration, animation
construction, playback scheduling, realtime Twinkly setup, random-show selection,
and color argument conversion in one file.

The goal is to split it into a `lyte/animate/` package without changing user
behavior. `lyte animate ...` should keep working while the internal boundaries get
clearer.

## Target Shape

Create these files:

- `lyte/animate/__init__.py`: public imports used by `lyte.cli` and preview.
- `lyte/animate/config.py`: `AnimateConfig`, `AnimationName`, `ANIMATIONS`, and
  validation.
- `lyte/animate/build.py`: `build_animation`, `rgb_arg`, and `colors_arg`.
- `lyte/animate/playback.py`: `run_animate`, `run_animation`,
  `run_animation_state`, `run_crossfade`, and `blend_frames`.
- `lyte/animate/random_show.py`: random animation selection, durations, overlap,
  and pattern logging.
- `lyte/animate/device.py`: Twinkly runtime setup helpers specific to animation
  playback: discovery, LED count, realtime preparation, frame send, and shutdown.
- `lyte/animate/__main__.py`: optional direct module entry point for
  `python -m lyte.animate`.

Keep `lyte/cli.py` as the tyro command table. It should import the same public
surface from `lyte.animate` that it imports today.

## Implementation Order

1. Create `lyte/animate/` with `config.py` and move the constants, type literal,
   dataclass, and validation there.
2. Move animation construction into `build.py`.
3. Move Twinkly setup/send/shutdown helpers into `device.py`.
4. Move random show helpers into `random_show.py`.
5. Move playback loops into `playback.py`.
6. Add `__init__.py` exports for the symbols used by `lyte.cli`,
   `scripts/lyte_preview.py`, and tests.
7. Remove the old single-file `lyte/animate.py` once imports have been moved.
8. Add `__main__.py` only after the package import surface is stable.

Run tests after each step that changes Python behavior. This split is mostly
movement, so tests should focus on existing behavior rather than new coverage.

## Boundaries

- Do not redesign the animation argument model during the split.
- Do not add compatibility for `scripts/lyte_animate.py`.
- Do not change animation defaults, random selection, frame timing, or shutdown
  behavior.
- Do not move generic Twinkly helpers out of `lyte.runtime` or `lyte.network` as
  part of this work.
- Keep preview using `build_animation` until preview has its own clearer
  animation selection path.

## Follow-Up Ideas

After the split, consider whether `lyte.cli.animate` can be generated more
directly from `AnimateConfig` without duplicating the dataclass fields in the CLI
wrapper. Do this only if tyro supports the shape cleanly and the help output stays
good.

## Additional work beyond the prompt

None.

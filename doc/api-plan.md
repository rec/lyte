# Lighting API Plan

The current animation API is easy to use, but it gives one object too many
jobs. An animation object currently tends to know what the animation is, how
many LEDs are attached, and how far playback has advanced. Those are separate
concerns.

The next API should split those concerns into three data classes:

1. `Animation`: immutable information describing the animation itself.
2. `Device`: immutable information describing the hardware.
3. `State`: mutable information describing playback progress.

This keeps animation data portable across installations. Two installations can
run the same animation data with different LED counts, frame rates, and physical
layouts. Buying a longer strand should require changing the device description,
not every animation data file.

## Core Types

`Device` describes hardware facts:

```python
class Device(BaseModel):
    model_config = ConfigDict(frozen=True)

    led_count: int
```

Future device fields can describe physical layout, RGB ordering, generation, or
other hardware properties, but the first version should stay narrow and include
only data already needed by the renderer.

`State` describes mutable playback progress:

```python
class State(BaseModel):
    frame: int = 0
    fps: float = 20.0
```

Every animation may define its own state class:

```python
class WeatherState(State):
    temp: float = 0.0
```

`Animation` describes immutable animation data and is generic on its state type:

```python
StateT = TypeVar("StateT", bound=State)


class Animation(BaseModel, Generic[StateT]):
    model_config = ConfigDict(frozen=True)

    def initial_state(self, device: Device) -> StateT:
        return State()

    def render(self, device: Device, state: StateT) -> NDArray[np.uint8]:
        ...
```

If `lyte` continues to target Python 3.11, the implementation should use
`Generic` and `TypeVar` rather than the Python 3.12 type-parameter syntax. A
default generic state type would require either a later Python version or an
explicit `typing_extensions` dependency, so the first implementation should use
`Animation[State]` where the base state is intended.

Derived animations can bind a specific state class:

```python
class WeatherAnimation(Animation[WeatherState]):
    colors: tuple[RGB, ...]

    def initial_state(self, device: Device) -> WeatherState:
        return WeatherState()

    def render(self, device: Device, state: WeatherState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        state.frame += 1
        return frame
```

`Animation` and `Device` are immutable. `render()` is allowed to mutate the
provided `State`.

## Frame Contract

The rendered frame remains the same transport-level object used today:

- `NDArray[np.uint8]`
- shape `(device.led_count, 3)`
- C-contiguous
- RGB channel order

The runner should validate this at the boundary before sending UDP packets.
Individual animations can rely on helper constructors to make valid frames
without repeating validation code.

## Runner Contract

Playback belongs outside animation classes. A runner owns:

- device discovery
- authentication
- realtime mode setup
- frame pacing
- retries
- crossfades
- shutdown/off behavior

The runner should call:

```python
state = animation.initial_state(device)
while playing:
    frame = animation.render(device, state)
    send(frame)
```

Frame rate is a runner concern. The same animation and state data can be played
at different FPS values without changing the animation object.

For animations whose speed is measured per second, the runner sets `state.fps`
after calling `initial_state()`. This keeps FPS out of immutable animation data
and hardware data while still letting render methods advance by the right
amount each frame.

## Migration Plan

1. Add `lyte.animation` with `Animation`, `Device`, and `State`.
2. Add a small runner-side validation helper for rendered frames.
3. Port one simple animation, probably `ColorFill`, to prove the API.
4. Port one stateful animation, probably `ColorWipe` or `RandomWalk`, to prove
   per-animation state classes.
5. Update `scripts/lyte_animate.py` to construct `Device`, create state once,
   and call `render()`.
6. Remove the local `Streamer` protocol once all script-supported animations use
   the new API.
7. Keep CLI options stable during the migration unless an option is directly
   tied to the old object model.

## Compatibility Notes

The old `next_frame()` API should not be kept as a parallel public API once the
migration is complete. During migration, temporary adapters are acceptable only
inside the script or tests, not as a second long-term animation interface.

The important conceptual rule is:

- `Animation` says what to draw.
- `Device` says what it is being drawn on.
- `State` says where playback currently is.
- The runner decides when frames are drawn and where they are sent.

## Additional work beyond the prompt

None.

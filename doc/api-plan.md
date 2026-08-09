# Lighting API Plan

## Current Runtime

Lyte requires Python 3.13. Its implemented pixel API separates immutable
animation and hardware descriptions from mutable playback state:

1. `Animation`: immutable description of what to render.
2. `Device`: immutable LED-count description.
3. `State`: mutable frame and FPS state.

`Animation.render(device, state)` returns a validated `float32` RGB frame.
The Twinkly driver performs the final byte encoding only at the transport
boundary. This document describes that current runtime contract; future
multi-protocol work is identified explicitly as a proposal.

## Core Types

`Device` describes the hardware facts currently required by the renderer:

```python
class Device(BaseModel, frozen=True):
    led_count: int
```

`State` describes mutable playback progress:

```python
class State(BaseModel):
    frame: int = 0
    fps: float = 20.0
```

Animations use Python 3.13 type parameters and bind their specific state type:

```python
class Animation[StateT: State](BaseModel, frozen=True):
    def initial_state(self, device: Device) -> StateT: ...

    def render(self, device: Device, state: StateT) -> NDArray[np.float32]: ...
```

`Animation` and `Device` are immutable. `render()` may mutate the supplied
`State`.

## Frame Contract

The current logical pixel-frame contract is:

- `NDArray[np.float32]`
- shape `(device.led_count, 3)`
- C-contiguous
- RGB channel order
- finite values; renderers conventionally produce values in `0.0..1.0`

`byte_light_frame_from_float()` clips, rounds, and encodes this logical frame
to the `uint8` payload expected by the current Twinkly realtime protocol. The
byte frame is an output detail, not an animation contract.

## Runner Contract

Playback lives outside animation classes. The current Twinkly runner owns
discovery, authentication, realtime setup, frame pacing, recovery, and
blackout cleanup:

```python
state = animation.initial_state(device)
while playing:
    logical_frame = animation.render(device, state)
    byte_frame = byte_light_frame_from_float(logical_frame)
    send(byte_frame)
```

The runner sets `state.fps` after `initial_state()` so animations can express
per-second motion without making FPS immutable animation data.

## Proposals

The following are not current runtime behavior:

- more `Device` fields for pixel layout or channel order
- a shared show runner for simultaneous protocols
- DMX fixture programs and universe buffers
- RGB-to-non-RGB channel conversion

Those features must preserve the current float32 pixel-frame contract rather
than silently changing it.

## Compatibility

`next_frame()` is not supported. The only public animation flow is
`Animation.render(device, state)`.

## Additional work beyond the prompt

None.

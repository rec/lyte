"""Run a selected Lyte animation on Twinkly generation 2 lights."""

import random
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Literal, NoReturn, cast

import numpy as np
import tyro
from numpy.typing import NDArray

from . import (
    Animation,
    Device,
    LyteClient,
    State,
    byte_light_frame_from_float,
    discover,
    validate_frame,
)
from .animations.bibliopixel import (
    DEFAULT_PATTERN,
    RGB,
    Alternates,
    ColorChase,
    ColorFade,
    ColorFill,
    ColorPattern,
    ColorWipe,
    FireFlies,
    HalvesRainbow,
    LarsonScanner,
    LinearRainbow,
    PartyMode,
    PixelPingPong,
    Pulse,
    Rainbow,
    RainbowCycle,
    SaberBlade,
    Searchlights,
    Twinkle,
    Wave,
    WhiteTwinkle,
)
from .animations.hamiltonian import Hamiltonian
from .animations.random_walk import RandomWalk
from .logging import log, log_error, log_status
from .network.session import (
    read_gestalt,
    set_mac_from_gestalt,
    set_off_mode_with_retry,
)
from .retry import RetryConfig
from .runtime import (
    authenticate_device,
    read_device_led_count,
    send_authenticated_frame,
    set_device_realtime_mode,
)

ANIMATIONS: tuple[str, ...] = (
    'alternates',
    'color_chase',
    'color_fade',
    'color_fill',
    'color_pattern',
    'color_wipe',
    'fire_flies',
    'halves_rainbow',
    'hamiltonian',
    'larson_rainbow',
    'larson_scanner',
    'linear_rainbow',
    'off',
    'party_mode',
    'pixel_ping_pong',
    'pulse',
    'rainbow',
    'rainbow_cycle',
    'random',
    'random_walk',
    'saber_blade',
    'searchlights',
    'twinkle',
    'wave',
    'wave_move',
    'white_twinkle',
)
AnimationName = Literal[
    'alternates',
    'color_chase',
    'color_fade',
    'color_fill',
    'color_pattern',
    'color_wipe',
    'fire_flies',
    'halves_rainbow',
    'hamiltonian',
    'larson_rainbow',
    'larson_scanner',
    'linear_rainbow',
    'off',
    'party_mode',
    'pixel_ping_pong',
    'pulse',
    'rainbow',
    'rainbow_cycle',
    'random',
    'random_walk',
    'saber_blade',
    'searchlights',
    'twinkle',
    'wave',
    'wave_move',
    'white_twinkle',
]
RANDOM_ANIMATIONS: tuple[str, ...] = tuple(
    a for a in ANIMATIONS if a not in ('off', 'random')
)
RANDOM_MIN_DURATION = 10.0
RANDOM_MAX_DURATION = 30.0
RANDOM_WALK_SPEED = 80.0
RANDOM_WALK_VARIANCE = 80.0
RANDOM_WALK_BOUNDS = (0.0, 255.0)
RANDOM_WALK_PERIOD = 6.0


@dataclass(frozen=True)
class AnimateConfig:
    animation: Annotated[AnimationName, tyro.conf.Positional] = 'random'
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float = 5.0
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    speed: float = 25
    fps: float = 20
    duration: float | None = None
    pre_fill: bool = False
    center_in: bool = False
    individual_pixel: bool = False
    step: int = 1
    start: int = 0
    end: int | None = None
    width: int = 1
    count: int = 1
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    total_pixels: int = 1
    fade_delay: int = 1
    density: int = 20
    max_bright: int = 255
    cycles: int = 2
    level_step: int = 5
    rainbow_inc: int = 4
    max_led: int | None = None
    reverse: bool = False
    n: int = 32
    order: str = 'rgb'
    inverted: str = ''
    variance: float = 1
    bounds: tuple[float, float] = (0, 180)
    color: tuple[int, int, int] | None = None
    color2: tuple[int, int, int] | None = None
    colors: tuple[int, ...] | None = None
    period: float = 0
    seed: int | None = None


def main() -> int:
    args = parse_args()
    return run_animate(args)


def run_animate(args: AnimateConfig) -> int:
    validate_args(args)
    host = args.host or discover_host(args.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=args.attempts,
        delay=args.retry_delay,
        backoff=args.retry_backoff,
    )
    client = LyteClient(host=host, timeout=args.timeout)
    if args.animation == 'off':
        return 0 if turn_off_device(client, retry, host) else 1

    led_count = read_led_count(client, retry, args.led_count, host)
    if led_count is None:
        return 1
    device = Device(led_count=led_count)
    if not prepare_device(client, retry, host):
        return 1

    try:
        if args.animation == 'random':
            run_random_animations(args, client, retry, host, device)
        else:
            run_animation(args, client, retry, host, device, args.duration)
    except KeyboardInterrupt:
        log()
        log('[ok] Stopped')
    finally:
        turn_off_streaming_device(client, retry, host)
    return 0


def parse_args(args: Sequence[str] | None = None) -> AnimateConfig:
    return tyro.cli(AnimateConfig, args=args)


def validate_args(args: AnimateConfig) -> None:
    if args.attempts < 1:
        fail('--attempts must be at least 1')
    if args.retry_delay < 0:
        fail('--retry-delay must not be negative')
    if args.retry_backoff < 1:
        fail('--retry-backoff must be at least 1')
    if args.fps <= 0:
        fail('--fps must be greater than zero')
    if args.speed < 0:
        fail('--speed must not be negative')
    if args.variance < 0:
        fail('--variance must not be negative')
    if args.bounds[0] >= args.bounds[1]:
        fail('--bounds must be ordered low high')
    if args.color is not None and any(c < 0 or c > 255 for c in args.color):
        fail('--color components must be between 0 and 255')
    if args.color2 is not None and any(c < 0 or c > 255 for c in args.color2):
        fail('--color2 components must be between 0 and 255')
    if args.colors is not None:
        if len(args.colors) % 3:
            fail('--colors must contain complete RGB triples')
        if any(c < 0 or c > 255 for c in args.colors):
            fail('--colors components must be between 0 and 255')
    if args.step < 1:
        fail('--step must be at least 1')
    if args.width < 1:
        fail('--width must be at least 1')
    if args.count < 1:
        fail('--count must be at least 1')
    if args.tail < 0:
        fail('--tail must not be negative')
    if args.chance < 0 or args.chance > 100:
        fail('--chance must be between 0 and 100')
    if args.min_speed < 1 or args.max_speed <= args.min_speed:
        fail('--min-speed and --max-speed must define a non-empty range')
    if args.total_pixels < 1:
        fail('--total-pixels must be at least 1')
    if args.fade_delay < 1:
        fail('--fade-delay must be at least 1')
    if args.density < 1:
        fail('--density must be at least 1')
    if args.max_bright < 1 or args.max_bright > 255:
        fail('--max-bright must be between 1 and 255')
    if args.cycles < 1:
        fail('--cycles must be at least 1')
    if args.level_step < 1:
        fail('--level-step must be at least 1')
    if args.rainbow_inc < 0:
        fail('--rainbow-inc must not be negative')
    if args.start < 0:
        fail('--start must not be negative')


def fail(message: str) -> NoReturn:
    sys.exit(message)


def run_random_animations(
    args: AnimateConfig,
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    device: Device,
) -> None:
    generator = random.Random(args.seed)
    stop_at = None if args.duration is None else time.monotonic() + args.duration
    current_args = random_animation_args(args, generator, None)
    current_animation = build_animation(current_args)
    current_state = current_animation.initial_state(device)
    current_state.fps = current_args.fps
    current_duration = random_pattern_duration(generator)
    previous_animation = current_args.animation
    log_pattern_start(current_args.animation, current_duration)

    while stop_at is None or time.monotonic() < stop_at:
        overlap_duration = random_overlap_duration(current_duration)
        solo_duration = clipped_duration(
            current_duration - overlap_duration,
            stop_at,
        )
        if solo_duration > 0:
            run_animation_state(
                current_animation,
                current_state,
                current_args,
                client,
                retry,
                host,
                device,
                solo_duration,
            )
        if stop_at is not None and time.monotonic() >= stop_at:
            return

        next_args = random_animation_args(args, generator, previous_animation)
        next_animation = build_animation(next_args)
        next_state = next_animation.initial_state(device)
        next_state.fps = next_args.fps
        next_duration = random_pattern_duration(generator)
        previous_animation = next_args.animation
        log_pattern_start(next_args.animation, next_duration)

        clipped_overlap_duration = clipped_duration(overlap_duration, stop_at)
        if clipped_overlap_duration > 0:
            run_crossfade(
                current_animation,
                current_state,
                next_animation,
                next_state,
                next_args,
                client,
                retry,
                host,
                device,
                clipped_overlap_duration,
            )
        current_args = next_args
        current_animation = next_animation
        current_state = next_state
        current_duration = next_duration


def random_pattern_duration(generator: random.Random) -> float:
    return generator.uniform(RANDOM_MIN_DURATION, RANDOM_MAX_DURATION)


def random_overlap_duration(duration: float) -> float:
    return duration / 2


def clipped_duration(duration: float, stop_at: float | None) -> float:
    if stop_at is None:
        return duration
    return min(duration, stop_at - time.monotonic())


def log_pattern_start(animation: str, duration: float) -> None:
    log_status(f'[pattern] {animation} for {duration:.1f} seconds')


def random_animation_args(
    args: AnimateConfig,
    generator: random.Random,
    previous_animation: str | None,
) -> AnimateConfig:
    choices = [a for a in RANDOM_ANIMATIONS if a != previous_animation]
    animation = cast(AnimationName, generator.choice(choices))
    seed = generator.randrange(0, 2**32)
    if animation == 'hamiltonian':
        return replace(args, animation=animation, seed=seed, n=256, speed=100)
    if animation == 'random_walk':
        return replace(
            args,
            animation=animation,
            seed=seed,
            speed=RANDOM_WALK_SPEED,
            variance=RANDOM_WALK_VARIANCE,
            bounds=RANDOM_WALK_BOUNDS,
            period=RANDOM_WALK_PERIOD,
            pre_fill=True,
        )
    return replace(args, animation=animation, seed=seed)


def run_animation(
    args: AnimateConfig,
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    duration: float | None,
) -> None:
    animation = build_animation(args)
    state = animation.initial_state(device)
    state.fps = args.fps
    run_animation_state(animation, state, args, client, retry, host, device, duration)


def run_animation_state(
    animation: Animation,
    state: State,
    args: AnimateConfig,
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    duration: float | None,
) -> None:
    frame_delay = 1 / args.fps
    stop_at = None if duration is None else time.monotonic() + duration
    log(
        '[ok] Streaming '
        f'{args.animation} frames to {host} for {device.led_count} LEDs '
        f'at {args.fps} FPS'
    )

    while stop_at is None or time.monotonic() < stop_at:
        started_at = time.monotonic()
        frame = byte_light_frame_from_float(
            validate_frame(device, animation.render(device, state))
        )
        send_realtime_frame(client, retry, host, frame)
        remaining = frame_delay - (time.monotonic() - started_at)
        if remaining > 0:
            time.sleep(remaining)


def run_crossfade(
    current_animation: Animation,
    current_state: State,
    next_animation: Animation,
    next_state: State,
    args: AnimateConfig,
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    duration: float,
) -> None:
    frame_delay = 1 / args.fps
    started_at = time.monotonic()
    stop_at = started_at + duration

    while time.monotonic() < stop_at:
        frame_started_at = time.monotonic()
        progress = (frame_started_at - started_at) / duration
        frame = blend_frames(
            validate_frame(device, current_animation.render(device, current_state)),
            validate_frame(device, next_animation.render(device, next_state)),
            progress,
        )
        send_realtime_frame(client, retry, host, byte_light_frame_from_float(frame))
        remaining = frame_delay - (time.monotonic() - frame_started_at)
        if remaining > 0:
            time.sleep(remaining)


def blend_frames(
    current_frame: NDArray[np.float32],
    next_frame: NDArray[np.float32],
    progress: float,
) -> NDArray[np.float32]:
    if current_frame.shape != next_frame.shape:
        raise ValueError('cannot blend frames with different shapes')
    progress = max(0.0, min(1.0, progress))
    return current_frame * (1.0 - progress) + next_frame * progress


def send_realtime_frame(
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    frame: NDArray[np.uint8],
) -> None:
    if client.token is None:
        sys.exit('Authentication token disappeared before frame send.')
    sent = send_authenticated_frame(
        client,
        host,
        frame,
        retry,
        f'UDP realtime frame send to {host}',
    )
    if sent is None:
        sys.exit(f'Could not send realtime frame to {host}.')


def build_animation(args: AnimateConfig) -> Animation:
    if args.animation == 'hamiltonian':
        return Hamiltonian(
            speed=args.speed,
            n=args.n,
            order=args.order,
            inverted=args.inverted,
            pre_fill=args.pre_fill,
        )
    if args.animation == 'color_chase':
        return ColorChase(
            color=rgb_arg(args.color, (255, 0, 0)),
            width=args.width,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_wipe':
        return ColorWipe(
            color=rgb_arg(args.color, (255, 0, 0)),
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_fill':
        return ColorFill(
            color=rgb_arg(args.color, (255, 0, 0)),
        )
    if args.animation == 'color_fade':
        return ColorFade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            level_step=args.level_step,
            start=args.start,
            end=args.end,
        )
    if args.animation == 'alternates':
        return Alternates(
            color1=rgb_arg(args.color, (255, 255, 255)),
            color2=rgb_arg(args.color2, (0, 0, 0)),
            max_led=args.max_led,
        )
    if args.animation == 'color_pattern':
        return ColorPattern(
            colors=colors_arg(args.colors),
            width=args.width,
            reverse=args.reverse,
        )
    if args.animation == 'party_mode':
        return PartyMode(colors=colors_arg(args.colors))
    if args.animation == 'fire_flies':
        return FireFlies(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            width=args.width,
            count=args.count,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation == 'saber_blade':
        return SaberBlade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            speed=round(args.speed),
        )
    if args.animation == 'rainbow':
        return Rainbow(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'rainbow_cycle':
        return RainbowCycle(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'linear_rainbow':
        return LinearRainbow(
            max_led=args.max_led,
            individual_pixel=args.individual_pixel,
            step=args.step,
        )
    if args.animation == 'halves_rainbow':
        return HalvesRainbow(
            max_led=args.max_led,
            center_out=not args.center_in,
            rainbow_inc=args.rainbow_inc,
            step=args.step,
        )
    if args.animation in ('larson_scanner', 'larson_rainbow'):
        return LarsonScanner(
            color=rgb_arg(args.color, (255, 0, 0)),
            tail=args.tail,
            start=args.start,
            end=args.end,
            step=args.step,
            rainbow=args.animation == 'larson_rainbow',
        )
    if args.animation == 'pulse':
        return Pulse(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            tail=args.tail,
            chance=args.chance,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            seed=args.seed,
        )
    if args.animation == 'pixel_ping_pong':
        return PixelPingPong(
            color=rgb_arg(args.color, (255, 255, 255)),
            max_led=args.max_led,
            total_pixels=args.total_pixels,
            fade_delay=args.fade_delay,
        )
    if args.animation == 'searchlights':
        return Searchlights(
            colors=colors_arg(args.colors, DEFAULT_PATTERN),
            tail=args.tail,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation in ('wave', 'wave_move'):
        return Wave(
            color=rgb_arg(args.color, (255, 0, 0)),
            cycles=args.cycles,
            start=args.start,
            end=args.end,
            moving=args.animation == 'wave_move',
        )
    if args.animation == 'twinkle':
        return Twinkle(
            colors=colors_arg(args.colors),
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    if args.animation == 'white_twinkle':
        return WhiteTwinkle(
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    color = (
        None
        if args.color is None
        else (float(args.color[0]), float(args.color[1]), float(args.color[2]))
    )
    return RandomWalk(
        speed=args.speed,
        variance=args.variance,
        bounds=(args.bounds[0], args.bounds[1]),
        color=color,
        period=args.period,
        pre_fill=args.pre_fill,
        seed=args.seed,
    )


def rgb_arg(value: Sequence[int] | None, default: RGB) -> RGB:
    if value is None:
        return default
    return value[0], value[1], value[2]


def colors_arg(
    value: Sequence[int] | None,
    default: tuple[RGB, ...] = DEFAULT_PATTERN,
) -> tuple[RGB, ...]:
    if value is None:
        return default
    return tuple(
        (value[i], value[i + 1], value[i + 2]) for i in range(0, len(value), 3)
    )


def read_led_count(
    client: LyteClient,
    retry: RetryConfig,
    configured_led_count: int | None,
    host: str,
) -> int | None:
    log(f'[step] Reading device info from {host}')
    led_count, gestalt = read_device_led_count(
        client,
        retry,
        configured_led_count,
        f'HTTP device info read from {host}',
    )
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    if configured_led_count is not None:
        log_status(f'[connected] {host}: using {configured_led_count} LEDs')
        return configured_led_count
    if led_count is None:
        sys.exit('Device did not report number_of_led; pass --led-count.')
    log_status(f'[connected] {host}: {led_count} LEDs')
    return led_count


def prepare_device(client: LyteClient, retry: RetryConfig, host: str) -> bool:
    log('[step] Authenticating')
    token = authenticate_device(
        client,
        retry,
        f'login and verify with {host}',
    )
    if token is None:
        sys.exit(f'Could not authenticate with {host}.')
    if client.token is None:
        sys.exit('Authentication succeeded without producing a token.')
    log_status(f'[connected] Authenticated with {host}')

    log('[step] Switching to realtime mode')
    realtime_response = set_device_realtime_mode(
        client,
        retry,
        f'switch {host} to realtime mode',
    )
    if realtime_response is None:
        sys.exit(f'Could not switch {host} to realtime mode.')
    log_status(f'[connected] {host} is in realtime mode')
    return True


def turn_off_device(client: LyteClient, retry: RetryConfig, host: str) -> bool:
    log(f'[step] Reading device info from {host}')
    gestalt = read_gestalt(client, retry, f'HTTP device info read from {host}')
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    set_mac_from_gestalt(client, gestalt)

    log('[step] Authenticating')
    token = authenticate_device(
        client,
        retry,
        f'login and verify with {host}',
    )
    if token is None:
        sys.exit(f'Could not authenticate with {host}.')
    log_status(f'[connected] Authenticated with {host}')

    log('[step] Switching device to off mode')
    response = set_off_mode_with_retry(
        client,
        retry,
        f'switch {host} to off mode',
    )
    if response is None:
        sys.exit(f'Could not switch {host} to off mode.')
    log(f'[ok] {host} is off')
    return True


def turn_off_streaming_device(
    client: LyteClient, retry: RetryConfig, host: str
) -> bool:
    log('[step] Switching device to off mode')
    response = set_off_mode_with_retry(
        client,
        retry,
        f'switch {host} to off mode',
    )
    if response is None:
        log_error(f'[failed] Could not switch {host} to off mode.')
        return False
    log(f'[ok] {host} is off')
    return True


def discover_host(timeout: float) -> str | None:
    log('[step] Discovering Twinkly devices')
    devices = list(discover(timeout=timeout))
    if not devices:
        log_error('[failed] No Twinkly discovery replies received.')
        log_error('Pass --host with the device IP address.')
        return None
    if len(devices) > 1:
        log('[warn] Multiple devices found; using the first one.')
    device = devices[0]
    log_status(f'[connected] Found {device.device_id} at {device.ip_address}')
    return device.ip_address


if __name__ == '__main__':
    raise SystemExit(main())

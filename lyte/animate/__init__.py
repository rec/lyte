from ..twinkly import realtime
from . import config, playback, random_show
from .build import build_animation, colors_arg, rgb_arg

discover_host = realtime.discover_host
prepare_device = realtime.prepare_device
read_led_count = realtime.read_led_count
send_realtime_frame = realtime.send_realtime_frame
turn_off_device = realtime.turn_off_device
turn_off_streaming_device = realtime.turn_off_streaming_device
ANIMATIONS = config.ANIMATIONS
RANDOM_ANIMATIONS = config.RANDOM_ANIMATIONS
RANDOM_MAX_DURATION = config.RANDOM_MAX_DURATION
RANDOM_MIN_DURATION = config.RANDOM_MIN_DURATION
RANDOM_WALK_BOUNDS = config.RANDOM_WALK_BOUNDS
RANDOM_WALK_PERIOD = config.RANDOM_WALK_PERIOD
RANDOM_WALK_SPEED = config.RANDOM_WALK_SPEED
RANDOM_WALK_VARIANCE = config.RANDOM_WALK_VARIANCE
AnimateConfig = config.AnimateConfig
AnimationName = config.AnimationName
validate_args = config.validate_args
blend_frames = playback.blend_frames
main = playback.main
parse_args = playback.parse_args
run_animate = playback.run_animate
run_animation = playback.run_animation
run_animation_state = playback.run_animation_state
run_crossfade = playback.run_crossfade
run_random_animations = playback.run_random_animations
clipped_duration = random_show.clipped_duration
log_pattern_start = random_show.log_pattern_start
random_animation_args = random_show.random_animation_args
random_overlap_duration = random_show.random_overlap_duration
random_pattern_duration = random_show.random_pattern_duration

__all__ = [
    'ANIMATIONS',
    'RANDOM_ANIMATIONS',
    'RANDOM_MAX_DURATION',
    'RANDOM_MIN_DURATION',
    'RANDOM_WALK_BOUNDS',
    'RANDOM_WALK_PERIOD',
    'RANDOM_WALK_SPEED',
    'RANDOM_WALK_VARIANCE',
    'AnimateConfig',
    'AnimationName',
    'blend_frames',
    'build_animation',
    'clipped_duration',
    'colors_arg',
    'discover_host',
    'log_pattern_start',
    'main',
    'parse_args',
    'prepare_device',
    'random_animation_args',
    'random_overlap_duration',
    'random_pattern_duration',
    'read_led_count',
    'rgb_arg',
    'run_animate',
    'run_animation',
    'run_animation_state',
    'run_crossfade',
    'run_random_animations',
    'send_realtime_frame',
    'turn_off_device',
    'turn_off_streaming_device',
    'validate_args',
]

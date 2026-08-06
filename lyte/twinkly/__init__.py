"""Twinkly protocol support for Lyte."""

# ruff: noqa: I001

from . import authentication
from . import client
from . import diagnostic
from . import inputs
from . import layout
from . import media
from . import mode
from . import output
from . import realtime
from . import session
from .command import prepare_authenticated_client, run_twinkly_command
from .discovery import DiscoveredDevice, discover, parse_discovery_response
from .frame import frame_packets_v3, frame_payload, send_frame_v3
from .networking import NetworkAction, run_network_control
from .timer import TimerAction, TwinklyTimer, run_timer_control

CHALLENGE_KEY = authentication.CHALLENGE_KEY
derive_key = authentication.derive_key
mac_bytes = authentication.mac_bytes
make_challenge_response = authentication.make_challenge_response
rc4 = authentication.rc4
AUTH_HEADER = client.AUTH_HEADER
TWINKLY_API_PREFIX = client.TWINKLY_API_PREFIX
AuthToken = client.AuthToken
TwinklyClient = client.TwinklyClient
TwinklyResponse = client.TwinklyResponse
DiagnosticCommandConfig = diagnostic.DiagnosticCommandConfig
DiagnosticConfig = diagnostic.DiagnosticConfig
TwinklyDeviceInfo = diagnostic.TwinklyDeviceInfo
TwinklyEndpointReport = diagnostic.TwinklyEndpointReport
authenticated_reports = diagnostic.authenticated_reports
read_endpoint = diagnostic.read_endpoint
run_diagnostic = diagnostic.run_diagnostic
run_diagnostic_command = diagnostic.run_diagnostic_command
MicAction = inputs.MicAction
MqttAction = inputs.MqttAction
MusicAction = inputs.MusicAction
run_mic_control = inputs.run_mic_control
run_mqtt_control = inputs.run_mqtt_control
run_music_control = inputs.run_music_control
LayoutAction = layout.LayoutAction
LedConfigAction = layout.LedConfigAction
TwinklyLayout = layout.TwinklyLayout
run_layout_control = layout.run_layout_control
run_led_config_control = layout.run_led_config_control
MovieAction = media.MovieAction
PlaylistAction = media.PlaylistAction
run_movie_control = media.run_movie_control
run_playlist_control = media.run_playlist_control
ColorAction = mode.ColorAction
EffectAction = mode.EffectAction
LedMode = mode.LedMode
ModeAction = mode.ModeAction
run_color_control = mode.run_color_control
run_effect_control = mode.run_effect_control
run_mode_control = mode.run_mode_control
OutputControl = output.OutputControl
OutputControlAction = output.OutputControlAction
read_output_control = output.read_output_control
run_output_control = output.run_output_control
write_output_control = output.write_output_control
discover_host = realtime.discover_host
prepare_device = realtime.prepare_device
read_led_count = realtime.read_led_count
send_realtime_frame = realtime.send_realtime_frame
turn_off_device = realtime.turn_off_device
turn_off_streaming_device = realtime.turn_off_streaming_device
authenticate_device = session.authenticate_device
authenticate_with_retry = session.authenticate_with_retry
led_count_from_gestalt = session.led_count_from_gestalt
read_device_led_count = session.read_device_led_count
read_gestalt = session.read_gestalt
send_authenticated_frame = session.send_authenticated_frame
send_frame_with_retry = session.send_frame_with_retry
set_device_realtime_mode = session.set_device_realtime_mode
set_mac_from_gestalt = session.set_mac_from_gestalt
set_off_mode_with_retry = session.set_off_mode_with_retry
set_realtime_mode_with_retry = session.set_realtime_mode_with_retry
turn_off_with_retry = session.turn_off_with_retry
twinkly_request_label = session.twinkly_request_label

__all__ = [
    'AUTH_HEADER',
    'AuthToken',
    'CHALLENGE_KEY',
    'ColorAction',
    'DiagnosticCommandConfig',
    'DiagnosticConfig',
    'DiscoveredDevice',
    'EffectAction',
    'LayoutAction',
    'LedConfigAction',
    'LedMode',
    'TwinklyClient',
    'TwinklyResponse',
    'MicAction',
    'ModeAction',
    'MovieAction',
    'MqttAction',
    'MusicAction',
    'NetworkAction',
    'OutputControl',
    'OutputControlAction',
    'PlaylistAction',
    'TWINKLY_API_PREFIX',
    'TimerAction',
    'TwinklyDeviceInfo',
    'TwinklyEndpointReport',
    'TwinklyLayout',
    'TwinklyTimer',
    'authenticate_device',
    'read_device_led_count',
    'send_authenticated_frame',
    'set_device_realtime_mode',
    'authenticate_with_retry',
    'authenticated_reports',
    'derive_key',
    'discover',
    'discover_host',
    'frame_packets_v3',
    'frame_payload',
    'led_count_from_gestalt',
    'mac_bytes',
    'make_challenge_response',
    'parse_discovery_response',
    'prepare_authenticated_client',
    'prepare_device',
    'rc4',
    'read_endpoint',
    'read_gestalt',
    'read_led_count',
    'read_output_control',
    'run_color_control',
    'run_diagnostic',
    'run_diagnostic_command',
    'run_effect_control',
    'run_layout_control',
    'run_led_config_control',
    'run_mic_control',
    'run_mode_control',
    'run_movie_control',
    'run_mqtt_control',
    'run_music_control',
    'run_network_control',
    'run_output_control',
    'run_playlist_control',
    'run_timer_control',
    'run_twinkly_command',
    'send_frame_v3',
    'send_frame_with_retry',
    'send_realtime_frame',
    'set_mac_from_gestalt',
    'set_off_mode_with_retry',
    'set_realtime_mode_with_retry',
    'turn_off_device',
    'turn_off_streaming_device',
    'turn_off_with_retry',
    'twinkly_request_label',
    'write_output_control',
]

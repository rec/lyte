"""Small dependency-free Lyte client."""

from . import animation, errors
from .animations import bibliopixel, hamiltonian
from .animations.random_walk import RandomWalk
from .preview import Layout, animation_document, render_animation_html
from .retry import RetryConfig, retry_call
from .twinkly import diagnostic, session
from .twinkly.client import TwinklyClient
from .twinkly.discovery import DiscoveredDevice, discover

Animation = animation.Animation
Device = animation.Device
State = animation.State
byte_light_frame_from_float = animation.byte_light_frame_from_float
float_color_from_rgb = animation.float_color_from_rgb
rgb_from_float_color = animation.rgb_from_float_color
solid_float_light_frame = animation.solid_float_light_frame
validate_byte_rgb_frame = animation.validate_byte_rgb_frame
validate_float_light_frame = animation.validate_float_light_frame
validate_frame = animation.validate_frame
Alternates = bibliopixel.Alternates
ColorChase = bibliopixel.ColorChase
ColorFade = bibliopixel.ColorFade
ColorFill = bibliopixel.ColorFill
ColorPattern = bibliopixel.ColorPattern
ColorWipe = bibliopixel.ColorWipe
FireFlies = bibliopixel.FireFlies
HalvesRainbow = bibliopixel.HalvesRainbow
LarsonScanner = bibliopixel.LarsonScanner
LinearRainbow = bibliopixel.LinearRainbow
PartyMode = bibliopixel.PartyMode
PixelPingPong = bibliopixel.PixelPingPong
Pulse = bibliopixel.Pulse
Rainbow = bibliopixel.Rainbow
RainbowCycle = bibliopixel.RainbowCycle
SaberBlade = bibliopixel.SaberBlade
Searchlights = bibliopixel.Searchlights
Twinkle = bibliopixel.Twinkle
Wave = bibliopixel.Wave
WhiteTwinkle = bibliopixel.WhiteTwinkle
Hamiltonian = hamiltonian.Hamiltonian
HamiltonianCounter = hamiltonian.HamiltonianCounter
HamiltonianState = hamiltonian.HamiltonianState
hamiltonian_colors = hamiltonian.hamiltonian_colors
AuthenticationError = errors.AuthenticationError
DiscoveryError = errors.DiscoveryError
LyteError = errors.LyteError
ProtocolError = errors.ProtocolError
UnsupportedEndpointError = errors.UnsupportedEndpointError
DiagnosticConfig = diagnostic.DiagnosticConfig
TwinklyDeviceInfo = diagnostic.TwinklyDeviceInfo
TwinklyEndpointReport = diagnostic.TwinklyEndpointReport
authenticate_with_retry = session.authenticate_with_retry
led_count_from_gestalt = session.led_count_from_gestalt
read_gestalt = session.read_gestalt
send_frame_with_retry = session.send_frame_with_retry
set_mac_from_gestalt = session.set_mac_from_gestalt
set_off_mode_with_retry = session.set_off_mode_with_retry
set_realtime_mode_with_retry = session.set_realtime_mode_with_retry
twinkly_request_label = session.twinkly_request_label

__all__ = [
    'AuthenticationError',
    'Alternates',
    'Animation',
    'byte_light_frame_from_float',
    'ColorChase',
    'ColorFade',
    'ColorFill',
    'ColorPattern',
    'ColorWipe',
    'FireFlies',
    'float_color_from_rgb',
    'HalvesRainbow',
    'DiscoveredDevice',
    'DiscoveryError',
    'Device',
    'DiagnosticConfig',
    'Hamiltonian',
    'HamiltonianCounter',
    'HamiltonianState',
    'hamiltonian_colors',
    'LarsonScanner',
    'LinearRainbow',
    'Layout',
    'PartyMode',
    'PixelPingPong',
    'ProtocolError',
    'Pulse',
    'Rainbow',
    'RainbowCycle',
    'RandomWalk',
    'SaberBlade',
    'Searchlights',
    'TwinklyClient',
    'LyteError',
    'RetryConfig',
    'State',
    'Twinkle',
    'TwinklyDeviceInfo',
    'Wave',
    'WhiteTwinkle',
    'TwinklyEndpointReport',
    'authenticate_with_retry',
    'animation_document',
    'discover',
    'retry_call',
    'led_count_from_gestalt',
    'read_gestalt',
    'render_animation_html',
    'rgb_from_float_color',
    'send_frame_with_retry',
    'set_off_mode_with_retry',
    'set_mac_from_gestalt',
    'set_realtime_mode_with_retry',
    'solid_float_light_frame',
    'UnsupportedEndpointError',
    'validate_byte_rgb_frame',
    'validate_float_light_frame',
    'validate_frame',
    'twinkly_request_label',
]

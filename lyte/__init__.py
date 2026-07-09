"""Small dependency-free Lyte client."""

from .bibliopixel import Alternates, ColorChase, ColorFill, ColorPattern, ColorWipe
from .client import LyteClient
from .discovery import DiscoveredDevice, discover
from .errors import (
    AuthenticationError,
    DiscoveryError,
    LyteError,
    ProtocolError,
)
from .hamiltonian import HamiltonianCounter, HamiltonianStreamer, hamiltonian_colors
from .random_walk import RandomWalk
from .retry import RetryConfig, retry_call
from .session import (
    authenticate_with_retry,
    led_count_from_gestalt,
    read_gestalt,
    send_frame_with_retry,
    set_mac_from_gestalt,
    set_realtime_mode_with_retry,
)

__all__ = [
    "AuthenticationError",
    "Alternates",
    "ColorChase",
    "ColorFill",
    "ColorPattern",
    "ColorWipe",
    "DiscoveredDevice",
    "DiscoveryError",
    "HamiltonianCounter",
    "HamiltonianStreamer",
    "hamiltonian_colors",
    "ProtocolError",
    "RandomWalk",
    "LyteClient",
    "LyteError",
    "RetryConfig",
    "authenticate_with_retry",
    "discover",
    "retry_call",
    "led_count_from_gestalt",
    "read_gestalt",
    "send_frame_with_retry",
    "set_mac_from_gestalt",
    "set_realtime_mode_with_retry",
]

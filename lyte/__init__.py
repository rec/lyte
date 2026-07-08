"""Small dependency-free Lyte client."""

from .client import LyteClient
from .discovery import DiscoveredDevice, discover
from .errors import (
    AuthenticationError,
    DiscoveryError,
    ProtocolError,
    LyteError,
)

__all__ = [
    "AuthenticationError",
    "DiscoveredDevice",
    "DiscoveryError",
    "ProtocolError",
    "LyteClient",
    "LyteError",
    "discover",
]

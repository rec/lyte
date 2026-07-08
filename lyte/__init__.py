"""Small dependency-free Lyte client."""

from .client import LyteClient
from .discovery import DiscoveredDevice, discover
from .errors import (
    AuthenticationError,
    DiscoveryError,
    ProtocolError,
    LyteError,
)
from .hamiltonian import HamiltonianCounter, HamiltonianStreamer

__all__ = [
    "AuthenticationError",
    "DiscoveredDevice",
    "DiscoveryError",
    "HamiltonianCounter",
    "HamiltonianStreamer",
    "ProtocolError",
    "LyteClient",
    "LyteError",
    "discover",
]

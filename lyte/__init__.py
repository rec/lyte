"""Small dependency-free Lyte client."""

from .client import LyteClient
from .discovery import DiscoveredDevice, discover
from .errors import (
    AuthenticationError,
    DiscoveryError,
    ProtocolError,
    LyteError,
)
from .hamiltonian import HamiltonianCounter, HamiltonianStreamer, hamiltonian_colors

__all__ = [
    "AuthenticationError",
    "DiscoveredDevice",
    "DiscoveryError",
    "HamiltonianCounter",
    "HamiltonianStreamer",
    "hamiltonian_colors",
    "ProtocolError",
    "LyteClient",
    "LyteError",
    "discover",
]

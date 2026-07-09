"""Small dependency-free Lyte client."""

from .client import LyteClient
from .discovery import DiscoveredDevice, discover
from .errors import (
    AuthenticationError,
    DiscoveryError,
    LyteError,
    ProtocolError,
)
from .hamiltonian import HamiltonianCounter, HamiltonianStreamer, hamiltonian_colors
from .retry import RetryConfig, retry_call

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
    "RetryConfig",
    "discover",
    "retry_call",
]

"""Exceptions for the small Lyte client."""


class LyteError(Exception):
    """Base error for Lyte operations."""


class DiscoveryError(LyteError):
    """Discovery datagram could not be sent or parsed."""


class ProtocolError(LyteError):
    """The device returned a response that does not match the protocol."""


class AuthenticationError(LyteError):
    """The authentication handshake failed."""

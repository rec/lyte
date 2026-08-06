"""Exceptions for the small Lyte client."""


class LyteError(Exception):
    """Base error for Lyte operations."""


class DiscoveryError(LyteError):
    """Discovery datagram could not be sent or parsed."""


class ProtocolError(LyteError):
    """The device returned a response that does not match the protocol."""


class UnsupportedEndpointError(ProtocolError):
    """The device does not support a Twinkly endpoint."""

    def __init__(self, path: str, text: str) -> None:
        self.path = path
        self.text = text
        super().__init__(f'Twinkly endpoint {path!r} is not supported: {text}')


class AuthenticationError(LyteError):
    """The authentication handshake failed."""

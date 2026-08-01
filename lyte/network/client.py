"""Small HTTP client for Lyte devices."""

from __future__ import annotations

import base64
import http.client
import json
import os
import time

from pydantic import BaseModel

from ..errors import AuthenticationError, ProtocolError
from .authentication import make_challenge_response

AUTH_HEADER = "X-Auth-Token"


class LyteResponse(BaseModel, frozen=True):
    http_status: int
    data: dict[str, object]


class AuthToken(BaseModel):
    value: str
    challenge_response: str
    expires_at: float | None

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()


class LyteClient(BaseModel):
    host: str
    mac: str | None = None
    timeout: float = 5.0
    token: AuthToken | None = None

    def authenticate(self) -> AuthToken:
        challenge = os.urandom(32)
        login = self.post(
            "login",
            {"challenge": base64.b64encode(challenge).decode()},
            authenticated=False,
        )
        data = login.data
        token = _required_str(data, "authentication_token")
        challenge_response = _required_str(data, "challenge-response")

        if self.mac is not None:
            expected = make_challenge_response(challenge, self.mac)
            if challenge_response != expected:
                raise AuthenticationError(
                    "Device challenge-response did not match the expected value"
                )

        expires_in = data.get("authentication_token_expires_in")
        expires_at = None
        if expires_in is not None:
            if not isinstance(expires_in, int | str):
                raise AuthenticationError(
                    "Login response did not contain numeric "
                    "'authentication_token_expires_in'"
                )
            expires_at = time.time() + int(expires_in)

        self.token = AuthToken(
            value=token,
            challenge_response=challenge_response,
            expires_at=expires_at,
        )
        self.post(
            "verify",
            {"challenge_response": challenge_response},
            authenticated=True,
        )
        return self.token

    def get(self, path: str, authenticated: bool = True) -> LyteResponse:
        return self.request("GET", path, authenticated=authenticated)

    def post(
        self,
        path: str,
        body: dict[str, object],
        authenticated: bool = True,
    ) -> LyteResponse:
        return self.request("POST", path, body=body, authenticated=authenticated)

    def set_realtime_mode(self) -> LyteResponse:
        return self.post("led/mode", {"mode": "rt"})

    def set_off_mode(self) -> LyteResponse:
        return self.post("led/mode", {"mode": "off"})

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        authenticated: bool = True,
    ) -> LyteResponse:
        payload = None
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers[AUTH_HEADER] = self._auth_token()
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Length"] = str(len(payload))

        connection = http.client.HTTPConnection(self.host, 80, timeout=self.timeout)
        try:
            connection.request(
                method,
                f"/xled/v1/{path}",
                body=payload,
                headers=headers,
            )
            response = connection.getresponse()
            raw = response.read()
        except OSError as err:
            raise ProtocolError(
                f"Could not reach Twinkly device at {self.host}: {err}"
            ) from err
        finally:
            connection.close()

        if response.status == 401:
            self.token = None
            raise AuthenticationError("Device rejected the authentication token")
        if response.status < 200 or response.status >= 300:
            text = raw.decode(errors="replace")
            raise ProtocolError(f"HTTP {response.status} from {self.host}: {text}")

        try:
            data = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError as err:
            raise ProtocolError(f"Device returned invalid JSON: {raw!r}") from err
        if not isinstance(data, dict):
            raise ProtocolError(f"Device returned a non-object JSON response: {data!r}")

        code = data.get("code")
        if code is not None and code != 1000:
            raise ProtocolError(f"Twinkly application code {code}: {data!r}")
        return LyteResponse(http_status=response.status, data=data)

    def _auth_token(self) -> str:
        if self.token is None or self.token.expired:
            self.authenticate()
        if self.token is None:
            raise AuthenticationError("Authentication did not produce a token")
        return self.token.value


def _required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise AuthenticationError(f"Login response did not contain string {key!r}")
    return value

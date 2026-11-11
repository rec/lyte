# tinkly

Low-level Python communication with Twinkly lights. Pydantic is the only
third-party runtime dependency. The package does not depend on lyte or NumPy.
Python 3.13 or newer is required.

This directory is a standalone Python project. Install it from the lyte checkout:

```sh
uv pip install ./tinkly
```

It can also be moved to a separate repository and installed from there. Lyte
currently uses it as a local editable dependency through its `pyproject.toml`.

## Device communication

The package provides UDP discovery, authentication, HTTP endpoint access, and
generation 2 realtime UDP v3 frame transmission. Existing device-facing types
retain the `Twinkly` spelling.

```python
from tinkly.client import TwinklyClient
from tinkly.discovery import discover
from tinkly.frame import send_frame_v3

devices = list(discover(timeout=2.0))
client = TwinklyClient(host=devices[0].ip_address)
info = client.get('gestalt', authenticated=False).data
client.mac = str(info['mac'])
token = client.authenticate()

client.set_realtime_mode()
frame = bytes((255, 0, 0)) * int(str(info['number_of_led']))
send_frame_v3(client.host, token.value, frame)
client.set_off_mode()
```

This illustrates one frame transmission. The caller controls repeated frame
delivery, pacing, token renewal, retries, reconnection, and shutdown. For repeated
transmissions, `send_frame_v3` accepts a caller-owned UDP socket as `output`.
UDP sending currently uses `socket.sendmsg`, which requires a platform providing
that method, such as macOS or Linux.

`TwinklyClient` exposes typed response records containing the HTTP status and
decoded JSON object. It provides named endpoint methods as well as `get`, `post`,
`post_bytes`, `delete`, and `request` for direct endpoint access. Protocol
exceptions are defined in `tinkly.errors`, under `TinklyError`.

## Frame buffers

Frames accept Python's buffer protocol through `collections.abc.Buffer`. Supply
C-contiguous unsigned bytes in RGB order, with three bytes per LED. Supported
inputs include `bytes`, `bytearray`, `array.array('B')`, `memoryview`, and
C-contiguous NumPy `uint8` arrays. Packet construction uses memoryviews without
copying pixel data. Keep mutable buffers unchanged until sending completes.

The transport treats the input as packed bytes; array shape validation belongs
to the caller. Array API compliance alone does not guarantee buffer support.
Arrays without a compatible host buffer must be converted by the caller.

## Tests

The tests use only the standard library and Pydantic. After installing the package,
run them from this directory:

```sh
python -m unittest discover -s tests
```

They use fake HTTP connections and sockets and do not contact lights. Playback,
animation, CLI commands, diagnostics, and retry policy remain in lyte.

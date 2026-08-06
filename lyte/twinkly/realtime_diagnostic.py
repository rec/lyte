"""Exercise a Lyte device with detailed diagnostics."""

import socket
import sys
import time
from dataclasses import dataclass
from typing import NoReturn

from ..animations.colors import solid_rgb_frame
from ..errors import DiscoveryError, ProtocolError
from ..logging import log, log_error
from ..retry import RetryConfig, retry_call
from ..runtime import (
    authenticate_device,
    read_device_led_count,
    send_authenticated_frame,
    set_device_realtime_mode,
)
from .client import TwinklyClient
from .discovery import (
    DEFAULT_BROADCAST,
    DISCOVERY_MESSAGE,
    DISCOVERY_PORT,
    DiscoveredDevice,
    parse_discovery_response,
)
from .session import (
    set_mac_from_gestalt,
)


@dataclass(frozen=True)
class RealtimeDiagnosticConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float = 0.1
    discovery_attempts: int = 20
    attempts: int = 10
    retry_delay: float = 0.5
    discovery_retry_delay: float = 0.05
    retry_backoff: float = 2.0
    discovery_backoff_after: int = 10
    led_count: int | None = None
    pause: float = 0.7

    @property
    def retry(self) -> RetryConfig:
        return RetryConfig(
            attempts=self.attempts,
            delay=self.retry_delay,
            backoff=self.retry_backoff,
            backoff_after=1,
        )

    @property
    def discovery_retry(self) -> RetryConfig:
        return RetryConfig(
            attempts=self.discovery_attempts,
            delay=self.discovery_retry_delay,
            backoff=self.retry_backoff,
            backoff_after=self.discovery_backoff_after,
        )


def run_realtime_diagnostic(config: RealtimeDiagnosticConfig) -> int:
    validate_realtime_diagnostic_config(config)
    log('Lyte diagnostic')
    log('==============================')
    log('This script uses only the Python standard library.')
    log('It will discover a device, authenticate, switch to realtime mode,')
    log('then send red, green, and blue UDP frames.')
    log()

    host = config.host or discover_one(
        config.discovery_timeout,
        config.discovery_retry,
    )
    if host is None:
        return 1

    client = TwinklyClient(host=host, timeout=config.timeout)
    print_step(f'Using device host {host}')

    if not get_unauthenticated_info(client, config.retry):
        return 1
    if not authenticate(client, config.retry):
        return 1
    led_count = config.led_count or detect_led_count(client, config.retry)
    if led_count is None:
        return 1
    if not set_realtime_mode(client, config.retry):
        return 1
    if not send_visible_test(client, host, led_count, config.pause, config.retry):
        return 1

    log()
    log('Diagnostic completed. The lights should have flashed red, green, and blue.')
    return 0


def validate_realtime_diagnostic_config(args: RealtimeDiagnosticConfig) -> None:
    if args.attempts < 1:
        fail('--attempts must be at least 1')
    if args.discovery_attempts < 1:
        fail('--discovery-attempts must be at least 1')
    if args.discovery_timeout <= 0:
        fail('--discovery-timeout must be greater than zero')
    if args.retry_delay < 0:
        fail('--retry-delay must not be negative')
    if args.discovery_retry_delay < 0:
        fail('--discovery-retry-delay must not be negative')
    if args.retry_backoff < 1:
        fail('--retry-backoff must be at least 1')
    if args.discovery_backoff_after < 1:
        fail('--discovery-backoff-after must be at least 1')


def fail(message: str) -> NoReturn:
    sys.exit(message)


def discover_one(timeout: float, retry: RetryConfig) -> str | None:
    print_step('Discovering Twinkly devices with UDP broadcast on port 5555')

    delay = retry.delay
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', 0))
        for attempt in range(1, retry.attempts + 1):
            device = discovery_attempt(
                sock,
                timeout,
                attempt,
                retry.attempts,
                report_failure=attempt == retry.attempts,
            )
            if device is not None:
                print_success(f'Found {device.device_id} at {device.ip_address}')
                return device.ip_address

            if attempt == retry.attempts:
                break
            log(
                '[retry] Waiting '
                f'{delay * 1000:.1f} ms before retrying UDP discovery broadcast.'
            )
            time.sleep(delay)
            if attempt >= retry.backoff_after:
                delay *= retry.backoff

    log('Check that the lights are powered on and joined to this network.')
    log('Check that this computer is on the same IPv4 network as the lights.')
    log('Some routers block broadcast traffic between WiFi clients.')
    log('Try passing --host with the device IP address.')
    return None


def discovery_attempt(
    sock: socket.socket,
    timeout: float,
    attempt: int,
    attempts: int,
    destination: str = DEFAULT_BROADCAST,
    report_failure: bool = True,
) -> DiscoveredDevice | None:
    log(f'[try] UDP discovery broadcast: attempt {attempt}/{attempts}')
    started_at = time.monotonic()
    deadline = started_at + timeout
    sock.sendto(DISCOVERY_MESSAGE, (destination, DISCOVERY_PORT))
    last_failure = ''

    while (remaining := deadline - time.monotonic()) > 0:
        sock.settimeout(remaining)
        try:
            data, _address = sock.recvfrom(256)
        except TimeoutError:
            break
        if data == DISCOVERY_MESSAGE:
            continue
        try:
            device = parse_discovery_response(data)
        except DiscoveryError as err:
            elapsed = (time.monotonic() - started_at) * 1000
            last_failure = (
                'UDP discovery broadcast received an invalid response on '
                f'attempt {attempt}/{attempts} after {elapsed:.1f} ms: {err}'
            )
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            print_success(
                'UDP discovery broadcast recovered on attempt '
                f'{attempt} after {elapsed:.1f} ms.'
            )
        else:
            print_success(f'UDP discovery broadcast completed in {elapsed:.1f} ms.')
        return device

    elapsed = (time.monotonic() - started_at) * 1000
    if report_failure:
        print_failure(
            last_failure
            or (
                'UDP discovery broadcast got no replies on '
                f'attempt {attempt}/{attempts} after {elapsed:.1f} ms.'
            )
        )
    return None


def get_unauthenticated_info(client: TwinklyClient, retry: RetryConfig) -> bool:
    print_step('Reading unauthenticated status, firmware, and device details')

    result = retry_call(
        'HTTP status, firmware, and gestalt reads',
        retry,
        lambda: (
            client.get('status', authenticated=False).data,
            client.get('fw/version', authenticated=False).data,
            client.get('gestalt', authenticated=False).data,
        ),
        (ProtocolError,),
    )
    if result is None:
        log('The host may not be a Twinkly device, or HTTP port 80 may be blocked.')
        return False
    status, firmware, gestalt = result

    print_success(f'Status: {status}')
    print_success(f'Firmware: {firmware}')
    print_success(f'Device name: {gestalt.get("device_name", "<missing>")}')
    print_success(f'MAC: {gestalt.get("mac", "<missing>")}')
    print_success(f'LED count: {gestalt.get("number_of_led", "<missing>")}')

    if not set_mac_from_gestalt(client, gestalt):
        log('Warning: gestalt did not include a MAC address.')
        log('Authentication can continue, but challenge-response cannot be verified.')
    return True


def authenticate(client: TwinklyClient, retry: RetryConfig) -> bool:
    print_step('Authenticating with login and verify')

    token = authenticate_device(
        client,
        retry,
        'login and verify',
    )
    if token is None:
        log('Check that no other app is rapidly invalidating the token.')
        log('Power-cycling the controller can clear stale auth state.')
        log('The firmware may not match generation 2 REST behavior.')
        return False
    print_success(f'Authenticated. Token expires at {token.expires_at!r}.')
    return True


def detect_led_count(client: TwinklyClient, retry: RetryConfig) -> int | None:
    print_step('Detecting LED count from gestalt')

    led_count, gestalt = read_device_led_count(
        client,
        retry,
        None,
        'HTTP gestalt read for LED count',
    )
    if gestalt is None:
        log('Pass --led-count if you know the number of LEDs.')
        return None

    if led_count is not None:
        print_success(f'Using {led_count} LEDs.')
        return led_count

    print_failure(f'Invalid number_of_led value: {gestalt.get("number_of_led")!r}')
    log('Pass --led-count with the exact LED count for your string.')
    return None


def set_realtime_mode(client: TwinklyClient, retry: RetryConfig) -> bool:
    print_step('Switching device to realtime mode')

    response = set_device_realtime_mode(
        client,
        retry,
        'HTTP switch to realtime mode',
    )
    if response is None:
        log('Realtime mode requires a valid auth token.')
        return False
    print_success(f'Realtime mode response: {response.data}')
    return True


def send_visible_test(
    client: TwinklyClient,
    host: str,
    led_count: int,
    pause: float,
    retry: RetryConfig,
) -> bool:
    if client.token is None:
        print_failure('Cannot send realtime frames without an auth token.')
        return False

    print_step('Sending red, green, and blue UDP frames to port 7777')
    colors = (('red', (255, 0, 0)), ('green', (0, 255, 0)), ('blue', (0, 0, 255)))
    for name, color in colors:
        frame = solid_rgb_frame(led_count, *color)
        bytes_sent = send_authenticated_frame(
            client,
            host,
            frame,
            retry,
            f'UDP realtime {name} frame send',
        )
        if bytes_sent is None:
            log('Check that UDP port 7777 is reachable from this computer.')
            log('Confirm this is generation 2 firmware new enough for v3 frames.')
            return False
        print_success(f'Sent {name} frame, {bytes_sent} bytes.')
        time.sleep(pause)
    return True


def print_step(message: str) -> None:
    log()
    log(f'[step] {message}')


def print_success(message: str) -> None:
    log(f'[ok] {message}')


def print_failure(message: str) -> None:
    log_error(f'[failed] {message}')

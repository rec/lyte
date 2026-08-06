from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from ..errors import AuthenticationError, ProtocolError, UnsupportedEndpointError
from ..fps_test import discover_host
from ..logging import log_error, log_status
from ..retry import RetryConfig, retry_call
from ..runtime import authenticate_device
from .client import LyteClient
from .realtime_diagnostic import RealtimeDiagnosticConfig, run_realtime_diagnostic
from .session import (
    set_mac_from_gestalt,
    turn_off_with_retry,
    twinkly_request_label,
)


class TwinklyDeviceInfo(BaseModel, frozen=True):
    raw: dict[str, object]
    device_name: str | None = None
    product_name: str | None = None
    product_code: str | None = None
    hardware_id: str | None = None
    firmware_family: str | None = None
    mac: str | None = None
    uuid: str | None = None
    led_profile: str | None = None
    led_count: int | None = None
    bytes_per_led: int | None = None
    frame_rate: float | None = None
    movie_capacity: int | None = None
    max_supported_led: int | None = None

    @classmethod
    def from_gestalt(cls, data: Mapping[str, object]) -> TwinklyDeviceInfo:
        return cls(
            raw=dict(data),
            device_name=optional_str(data, 'device_name'),
            product_name=optional_str(data, 'product_name'),
            product_code=optional_str(data, 'product_code'),
            hardware_id=optional_str(data, 'hw_id'),
            firmware_family=optional_str(data, 'fw_family'),
            mac=optional_str(data, 'mac'),
            uuid=optional_str(data, 'uuid'),
            led_profile=optional_str(data, 'led_profile'),
            led_count=optional_int(data, 'number_of_led'),
            bytes_per_led=optional_int(data, 'bytes_per_led'),
            frame_rate=optional_float(data, 'frame_rate'),
            movie_capacity=optional_int(data, 'movie_capacity'),
            max_supported_led=optional_int(data, 'max_supported_led'),
        )


class TwinklyEndpointReport(BaseModel, frozen=True):
    name: str
    path: str
    supported: bool
    data: dict[str, object] | None = None
    error: str | None = None


@dataclass(frozen=True)
class DiagnosticConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0


@dataclass(frozen=True)
class DiagnosticCommandConfig:
    realtime: bool = False
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    discovery_attempts: int = 20
    discovery_retry_delay: float = 0.05
    discovery_backoff_after: int = 10
    led_count: int | None = None
    pause: float = 0.7


def run_diagnostic_command(config: DiagnosticCommandConfig) -> int:
    if config.realtime:
        return run_realtime_diagnostic(
            RealtimeDiagnosticConfig(
                host=config.host,
                timeout=config.timeout,
                discovery_timeout=(
                    0.1
                    if config.discovery_timeout is None
                    else config.discovery_timeout
                ),
                discovery_attempts=config.discovery_attempts,
                attempts=config.attempts,
                retry_delay=config.retry_delay,
                discovery_retry_delay=config.discovery_retry_delay,
                retry_backoff=config.retry_backoff,
                discovery_backoff_after=config.discovery_backoff_after,
                led_count=config.led_count,
                pause=config.pause,
            )
        )
    return run_diagnostic(
        DiagnosticConfig(
            host=config.host,
            timeout=config.timeout,
            discovery_timeout=config.discovery_timeout,
            attempts=config.attempts,
            retry_delay=config.retry_delay,
            retry_backoff=config.retry_backoff,
        )
    )


def run_diagnostic(config: DiagnosticConfig) -> int:
    validate_diagnostic_config(config)
    host = config.host or discover_host(config.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    client = LyteClient(host=host, timeout=config.timeout)
    log_status(f'[diagnostic] Host: {host}')

    gestalt = read_endpoint(
        client,
        retry,
        'gestalt',
        'GET',
        'gestalt',
        lambda: client.get('gestalt', authenticated=False).data,
    )
    if not gestalt.supported or gestalt.data is None:
        report_endpoint(gestalt)
        return 1

    device = TwinklyDeviceInfo.from_gestalt(gestalt.data)
    set_mac_from_gestalt(client, gestalt.data)
    report_device_info(device)

    unauthenticated_reports = (
        read_endpoint(
            client,
            retry,
            'firmware',
            'GET',
            'fw/version',
            lambda: client.get_firmware_version().data,
        ),
        read_endpoint(
            client,
            retry,
            'status',
            'GET',
            'status',
            lambda: client.get_status().data,
        ),
    )
    for report in unauthenticated_reports:
        report_endpoint(report)

    if authenticate_device(client, retry, twinkly_request_label('POST', 'login', host)):
        off_succeeded = True
        try:
            for report in authenticated_reports(client, retry):
                report_endpoint(report)
        finally:
            off_succeeded = turn_off_with_retry(client, retry, host)
        if not off_succeeded:
            return 1
    else:
        log_error('[diagnostic] Authenticated endpoint probes skipped.')
        return 1
    return 0


def validate_diagnostic_config(config: DiagnosticConfig) -> None:
    if config.discovery_timeout is not None and config.discovery_timeout <= 0:
        sys.exit('--discovery-timeout must be greater than zero')
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')


def authenticated_reports(
    client: LyteClient,
    retry: RetryConfig,
) -> tuple[TwinklyEndpointReport, ...]:
    return (
        read_endpoint(
            client,
            retry,
            'layout',
            'GET',
            'led/layout/full',
            lambda: client.get_layout_full().data,
        ),
        read_endpoint(
            client,
            retry,
            'led-config',
            'GET',
            'led/config',
            lambda: client.get_led_config().data,
        ),
        read_endpoint(
            client,
            retry,
            'mode',
            'GET',
            'led/mode',
            lambda: client.get_led_mode().data,
        ),
        read_endpoint(
            client,
            retry,
            'timer',
            'GET',
            'timer',
            lambda: client.get_timer().data,
        ),
        read_endpoint(
            client,
            retry,
            'movie-config',
            'GET',
            'led/movie/config',
            lambda: client.get_movie_config().data,
        ),
        read_endpoint(
            client,
            retry,
            'movies',
            'GET',
            'movies',
            lambda: client.get_movies().data,
        ),
        read_endpoint(
            client,
            retry,
            'current-movie',
            'GET',
            'led/movies/current',
            lambda: client.get_current_movie().data,
        ),
        read_endpoint(
            client,
            retry,
            'playlist',
            'GET',
            'playlist',
            lambda: client.get_playlist().data,
        ),
        read_endpoint(
            client,
            retry,
            'current-playlist-entry',
            'GET',
            'playlist/current',
            lambda: client.get_current_playlist_entry().data,
        ),
        read_endpoint(
            client,
            retry,
            'network-status',
            'GET',
            'network/status',
            lambda: client.get_network_status().data,
        ),
        read_endpoint(
            client,
            retry,
            'network-scan',
            'GET',
            'network/scan',
            lambda: client.get_network_scan().data,
        ),
        read_endpoint(
            client,
            retry,
            'network-scan-results',
            'GET',
            'network/scan_results',
            lambda: client.get_network_scan_results().data,
        ),
        read_endpoint(
            client,
            retry,
            'mqtt-config',
            'GET',
            'mqtt/config',
            lambda: client.get_mqtt_config().data,
        ),
        read_endpoint(
            client,
            retry,
            'mic-config',
            'GET',
            'mic/config',
            lambda: client.get_mic_config().data,
        ),
        read_endpoint(
            client,
            retry,
            'mic-sample',
            'GET',
            'mic/sample',
            lambda: client.get_mic_sample().data,
        ),
        read_endpoint(
            client,
            retry,
            'music-drivers',
            'GET',
            'music/drivers',
            lambda: client.get_music_drivers().data,
        ),
        read_endpoint(
            client,
            retry,
            'music-driver-sets',
            'GET',
            'music/drivers/sets',
            lambda: client.get_music_driver_sets().data,
        ),
        read_endpoint(
            client,
            retry,
            'current-music-driver-set',
            'GET',
            'music/drivers/sets/current',
            lambda: client.get_current_music_driver_set().data,
        ),
        read_endpoint(
            client,
            retry,
            'color',
            'GET',
            'led/color',
            lambda: client.get_led_color().data,
        ),
        read_endpoint(
            client,
            retry,
            'effects',
            'GET',
            'led/effects',
            lambda: client.get_effects().data,
        ),
        read_endpoint(
            client,
            retry,
            'current-effect',
            'GET',
            'led/effects/current',
            lambda: client.get_current_effect().data,
        ),
        read_endpoint(
            client,
            retry,
            'brightness',
            'GET',
            'led/out/brightness',
            lambda: client.get_brightness().data,
        ),
        read_endpoint(
            client,
            retry,
            'saturation',
            'GET',
            'led/out/saturation',
            lambda: client.get_saturation().data,
        ),
        read_endpoint(
            client,
            retry,
            'device-name',
            'GET',
            'device_name',
            lambda: client.get_device_name().data,
        ),
        read_endpoint(
            client,
            retry,
            'summary',
            'GET',
            'summary',
            lambda: client.get_summary().data,
        ),
        read_endpoint(
            client,
            retry,
            'echo',
            'POST',
            'echo',
            lambda: client.echo({'message': 'lyte diagnostic'}).data,
        ),
    )


def read_endpoint(
    client: LyteClient,
    retry: RetryConfig,
    name: str,
    method: str,
    path: str,
    request: Callable[[], dict[str, object]],
) -> TwinklyEndpointReport:
    def read_once() -> TwinklyEndpointReport:
        try:
            return TwinklyEndpointReport(
                name=name,
                path=path,
                supported=True,
                data=request(),
            )
        except UnsupportedEndpointError as err:
            return TwinklyEndpointReport(
                name=name,
                path=path,
                supported=False,
                error=err.text,
            )

    result = retry_call(
        twinkly_request_label(method, path, client.host),
        retry,
        read_once,
        (AuthenticationError, ProtocolError),
    )
    if result is not None:
        return result
    return TwinklyEndpointReport(
        name=name,
        path=path,
        supported=False,
        error='request failed',
    )


def report_device_info(device: TwinklyDeviceInfo) -> None:
    log_status(f'[diagnostic] Device name: {display(device.device_name)}')
    log_status(f'[diagnostic] Product: {display(device.product_name)}')
    log_status(f'[diagnostic] Product code: {display(device.product_code)}')
    log_status(f'[diagnostic] Hardware ID: {display(device.hardware_id)}')
    log_status(f'[diagnostic] Firmware family: {display(device.firmware_family)}')
    log_status(f'[diagnostic] MAC: {display(device.mac)}')
    log_status(f'[diagnostic] UUID: {display(device.uuid)}')
    log_status(f'[diagnostic] LED profile: {display(device.led_profile)}')
    log_status(f'[diagnostic] LED count: {display(device.led_count)}')
    log_status(f'[diagnostic] Bytes per LED: {display(device.bytes_per_led)}')
    log_status(f'[diagnostic] Frame rate: {display(device.frame_rate)}')
    log_status(f'[diagnostic] Movie capacity: {display(device.movie_capacity)}')
    log_status(f'[diagnostic] Max supported LED: {display(device.max_supported_led)}')


def report_endpoint(report: TwinklyEndpointReport) -> None:
    if report.supported:
        log_status(f'[diagnostic] {report.name}: {report.data}')
    else:
        log_error(f'[diagnostic] {report.name}: unsupported or failed: {report.error}')


def optional_str(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None


def optional_int(data: Mapping[str, object], key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, int):
        return value
    return None


def optional_float(data: Mapping[str, object], key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


def display(value: object | None) -> object:
    if value is None:
        return '<missing>'
    return value

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import mido
import numpy as np
import pytest
from numpy.typing import NDArray
from pydantic import ValidationError
from reccy.errors import ReccyError
from reccy.protocol import ipc, rpc
from reccy.reccy import Reccy
from reccy.services.models import StatusResult
from ufor import library_files, light_animation, modulation
from ufor.control import Scope
from ufor.interface import ParameterExport
from ufor.library import Entry, Library

from lyte import (
    installation,
    installation_config,
    installation_playback,
    metrics,
    runtime_control,
    show,
)
from lyte.twinkly import diagnostic


def test_parse_installation_accepts_selectable_animations() -> None:
    config = installation_config.parse_installation(example_installation())

    assert config.twinkly['left'].product_name == 'Dots'
    assert config.animations['across'].outputs == {'light': 'left + right'}
    assert config.initial_animation == 'across'


def test_controlled_animation_requires_midi_configuration() -> None:
    data = example_installation()
    animations = data['animations']
    assert isinstance(animations, dict)
    across = animations['across']
    assert isinstance(across, dict)
    across['activation'] = 'note'

    with pytest.raises(ValidationError, match='require MIDI'):
        installation_config.parse_installation(data)


def test_animation_defaults_are_applied_unless_overridden() -> None:
    data = example_installation() | {
        'midi': {'channel': 1},
        'animation_defaults': {
            'activation': 'note',
            'controls': [{'source': 'breath', 'parameter': 'brightness'}],
        },
    }
    animations = data['animations']
    assert isinstance(animations, dict)
    separate = animations['separate']
    assert isinstance(separate, dict)
    separate['activation'] = 'always'
    separate['controls'] = []

    config = installation_config.parse_installation(data)

    assert config.animations['across'].activation == 'note'
    assert config.animations['across'].controls[0].parameter == 'brightness'
    assert config.animations['separate'].activation == 'always'
    assert config.animations['separate'].controls == []


def test_midi_controls_map_canonical_and_table_values() -> None:
    performance = runtime_control.MidiPerformance(note=61, velocity=64, breath=32)

    velocity = installation_config.ParameterControl(
        source='velocity', parameter='gain', output=[0.0, 2.0]
    )
    note = installation_config.ParameterControl(
        source='note', parameter='red', values=[0.25, 0.75]
    )

    assert velocity.map(performance) == pytest.approx(128 / 127)
    assert note.map(performance) == 0.75


def test_example_installation_is_valid() -> None:
    config = installation_config.load_installation(Path('examples/installation.toml'))

    assert config.initial_animation == 'tree_show'


@pytest.mark.parametrize(
    'mapping',
    [
        {'output': [0, 128]},
        {'values': [0, 60, 128]},
        {'values': [float('nan')]},
        {'output': [0, float('inf')]},
    ],
)
def test_invalid_midi_range_fails_before_discovery(
    mapping: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = installation_config.parse_installation(
        {
            'library_config': 'patches/wearable-library.toml',
            'twinkly': {'left': {}},
            'midi': {'channel': 1},
            'initial_animation': 'controlled',
            'animations': {
                'controlled': {
                    'selector': 'wearable:/breath_walker.toml',
                    'outputs': {'light': 'left'},
                    'controls': [{'source': 'note', 'parameter': 'note', **mapping}],
                }
            },
        }
    )
    discover = Mock(side_effect=AssertionError('discovery must not start'))
    monkeypatch.setattr(installation, 'discover_assignments', discover)
    with pytest.raises(
        installation_config.InstallationFileError, match='control note: mapped value'
    ):
        installation.build_service(config)
    discover.assert_not_called()


def test_construction_only_midi_target_fails_before_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    score = library.composition('aurora').scores['examples:/aurora.toml'].score
    assert isinstance(score, light_animation.AnimationScore)
    target = modulation.Target(name='animation', parameter='speed')
    controlled = score.model_copy(
        update={
            'parameters': [ParameterExport(name='speed', binding=target)],
            'body': score.body.model_copy(
                update={
                    'modulation': modulation.Modulation(
                        parameters=[
                            modulation.Parameter(
                                target=target,
                                unit=modulation.Unit.ratio,
                                scope=Scope.part,
                                minimum=0,
                                maximum=2,
                                default=1,
                            ),
                        ]
                    )
                }
            ),
        }
    )
    library = Library(
        [Entry(library='test', address='/aurora.toml', name='aurora', score=controlled)]
    )
    monkeypatch.setattr(
        installation_playback.library_files, 'read_library', lambda path: library
    )
    discover = Mock(side_effect=AssertionError('discovery must not start'))
    monkeypatch.setattr(installation, 'discover_assignments', discover)
    config = installation_config.parse_installation(
        {
            'twinkly': {'left': {}},
            'midi': {'channel': 1},
            'initial_animation': 'controlled',
            'animations': {
                'controlled': {
                    'selector': 'aurora',
                    'outputs': {'light': 'left'},
                    'controls': [
                        {'source': 'breath', 'parameter': 'speed', 'output': [0, 2]}
                    ],
                }
            },
        }
    )
    with pytest.raises(
        installation_config.InstallationFileError, match='construction-only'
    ):
        installation.build_service(config)
    discover.assert_not_called()


def test_showco_installation_is_valid() -> None:
    config = installation_config.load_installation(
        Path('patches/showco-installation.toml')
    )

    assert list(config.twinkly) == ['dots', 'strings']
    assert config.animations['tree_show'].outputs == {'light': 'dots + strings'}


def test_installation_rejects_legacy_network_configuration() -> None:
    data = example_installation()
    twinkly = data['twinkly']
    assert isinstance(twinkly, dict)
    left = twinkly['left']
    assert isinstance(left, dict)
    left['host'] = '192.168.1.23'

    with pytest.raises(ValidationError, match='host'):
        installation_config.parse_installation(data)


def test_installation_rejects_missing_string_binding() -> None:
    data = example_installation()
    animations = data['animations']
    assert isinstance(animations, dict)
    across = animations['across']
    assert isinstance(across, dict)
    across['outputs'] = {'light': 'left'}

    with pytest.raises(ValueError, match="does not bind string 'right'"):
        installation_config.parse_installation(data)


@pytest.mark.parametrize(
    ('value', 'message'),
    [
        ('left+right', 'spaces around'),
        ('left + right * back', 'cannot mix'),
        (' left', 'leading or trailing'),
        ('left + left', 'more than once'),
        ('other', 'unknown string'),
    ],
)
def test_output_expression_rejects_ambiguous_syntax(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        installation_config.parse_output_expression(value, {'left', 'right', 'back'})


def test_concatenated_output_scales_then_partitions() -> None:
    source = np.array([[0, 0, 0], [100, 0, 0], [200, 0, 0]], dtype=np.uint8)
    expression = installation_config.parse_output_expression(
        'left + right', {'left', 'right'}
    )

    frames = installation_playback.distribute_frame(
        source, expression, {'left': 2, 'right': 3}
    )

    assert [name for name, _ in frames] == ['left', 'right']
    assert frames[0][1].tolist() == [[0, 0, 0], [0, 0, 0]]
    assert frames[1][1].tolist() == [[100, 0, 0], [100, 0, 0], [200, 0, 0]]


def test_mirrored_output_scales_each_copy() -> None:
    source = np.array([[0, 0, 0], [255, 0, 0]], dtype=np.uint8)
    expression = installation_config.parse_output_expression(
        'left * right', {'left', 'right'}
    )

    frames = installation_playback.distribute_frame(
        source, expression, {'left': 3, 'right': 5}
    )

    assert [frame.shape for _, frame in frames] == [(3, 3), (5, 3)]
    assert frames[0][1].tolist() == [[0, 0, 0], [0, 0, 0], [255, 0, 0]]
    assert frames[1][1].tolist() == [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
        [255, 0, 0],
        [255, 0, 0],
    ]


def test_mirrored_binding_renders_once() -> None:
    prepared = CountingPrepared()
    active = object.__new__(installation_playback.ActiveAnimation)
    active.led_counts = {
        'left': 2,
        'right': 3,
    }
    active.definition = installation_config.BoundAnimation(
        selector='examples:/composition.toml',
        outputs={'light': 'left * right'},
    )
    active.performance = runtime_control.MidiPerformance()
    active.started_at = None
    active.bindings = [
        installation_playback.PreparedBinding(
            output_name='light',
            expression=installation_config.parse_output_expression(
                'left * right', active.led_counts
            ),
            prepared=prepared,
        )
    ]

    frames = active.render(0)

    assert prepared.render_count == 1
    assert [frame.shape for _, frame in frames] == [(2, 3), (3, 3)]


@pytest.mark.parametrize('send_rate', [10, 20, 30])
def test_installation_preserves_score_frames_at_different_send_rates(
    send_rate: int,
) -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    active = installation_playback.ActiveAnimation(
        'aurora',
        installation_config.BoundAnimation(
            selector='aurora', outputs={'light': 'left'}
        ),
        library,
        {'left': 250},
    )
    reference = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='aurora')
    )
    expected = None
    for i in range(send_rate + 1):
        now = float(Fraction(i, send_rate))
        target = int(Fraction(str(now)) * reference.rate)
        while reference.tick <= target:
            expected = reference.byte_frame(wired=True)
        np.testing.assert_array_equal(active.render(now)[0][1], expected)


def test_score_catches_up_after_a_delay_and_restarts_on_a_note() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    active = installation_playback.ActiveAnimation(
        'aurora',
        installation_config.BoundAnimation(
            selector='aurora', outputs={'light': 'left'}, activation='note'
        ),
        library,
        {'left': 250},
    )
    assert not active.render(100)[0][1].any()
    active.apply_performance(runtime_control.MidiPerformance(note=60), restart=True)
    first = active.render(200)[0][1].copy()
    reference = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='aurora')
    )
    for _ in range(21):
        expected = reference.byte_frame(wired=True)
    np.testing.assert_array_equal(active.render(201)[0][1], expected)
    active.apply_performance(runtime_control.MidiPerformance(note=62), restart=True)
    np.testing.assert_array_equal(active.render(202)[0][1], first)


def test_active_animation_applies_midi_controls() -> None:
    prepared = CountingPrepared()
    active = object.__new__(installation_playback.ActiveAnimation)
    active.definition = installation_config.BoundAnimation(
        selector='examples:/composition.toml',
        outputs={'light': 'left'},
        controls=[
            installation_config.ParameterControl(
                source='breath', parameter='brightness', output=[0.0, 2.0]
            )
        ],
    )
    active.bindings = [
        installation_playback.PreparedBinding(
            output_name='light',
            expression=installation_config.OutputExpression(['left'], 'single'),
            prepared=prepared,
        )
    ]

    active.apply_performance(runtime_control.MidiPerformance(note=60, breath=64))

    assert prepared.parameters['brightness'] == pytest.approx(128 / 127)


def test_assignment_uses_single_remaining_device() -> None:
    dots = discovered('192.168.1.10', product_name='Twinkly Dots')
    strings = discovered('192.168.1.11', product_name='Twinkly Strings')

    assignment = installation.assign_twinkly_devices(
        {
            'left': installation_config.TwinklySelector(product_name='dots'),
            'right': installation_config.TwinklySelector(),
        },
        [dots, strings],
    )

    assert assignment == {'left': dots, 'right': strings}


def test_assignment_rejects_indistinguishable_devices() -> None:
    devices = [
        discovered('192.168.1.10', product_name='Twinkly Dots'),
        discovered('192.168.1.11', product_name='Twinkly Dots'),
    ]

    with pytest.raises(installation_config.InstallationFileError, match='ambiguous'):
        installation.assign_twinkly_devices(
            {
                'left': installation_config.TwinklySelector(),
                'right': installation_config.TwinklySelector(),
            },
            devices,
        )


@pytest.mark.parametrize('value', [0, -1, float('inf'), float('nan')])
def test_startup_timeout_requires_a_positive_finite_value(value: float) -> None:
    with pytest.raises(ValidationError, match='startup_timeout'):
        installation_config.parse_installation(
            example_installation() | {'startup_timeout': value}
        )


def test_missing_devices_stop_at_the_startup_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SimpleNamespace(now=0.0)

    def advance(seconds: float) -> None:
        clock.now += seconds

    def scan(seconds: float) -> list[installation.discovery.DiscoveredDevice]:
        advance(seconds)
        return []

    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(installation.time, 'sleep', advance)
    monkeypatch.setattr(installation.discovery, 'discover', scan)
    config = installation_config.parse_installation(
        example_installation() | {'startup_timeout': 2, 'discovery_timeout': 0.75}
    )

    with pytest.raises(
        installation_config.InstallationFileError, match='startup_timeout=2s'
    ):
        installation.discover_assignments(config)
    assert clock.now == 2


def test_ambiguous_discovery_fails_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = [
        installation.discovery.DiscoveredDevice(
            ip_address=f'192.168.1.{i}', device_id=str(i)
        )
        for i in [10, 11]
    ]
    scan = Mock(return_value=devices)
    monkeypatch.setattr(installation.discovery, 'discover', scan)
    monkeypatch.setattr(
        installation.session,
        'read_gestalt',
        Mock(return_value={'product_name': 'Dots'}),
    )
    with pytest.raises(installation.AmbiguousAssignmentError):
        installation.discover_assignments(
            installation_config.parse_installation(example_installation())
        )
    scan.assert_called_once()


def test_identification_cannot_extend_the_discovery_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SimpleNamespace(now=10.0)

    def identify(client: object, retry: object, label: str, deadline: float) -> None:
        assert deadline == 12
        clock.now = deadline

    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(
        installation.discovery,
        'discover',
        lambda seconds: [
            installation.discovery.DiscoveredDevice(
                ip_address='192.168.1.10', device_id='one'
            )
        ],
    )
    monkeypatch.setattr(installation.session, 'read_gestalt', identify)
    with pytest.raises(
        installation_config.InstallationFileError, match='startup_timeout=2s'
    ):
        installation.discover_assignments(
            installation_config.parse_installation(
                example_installation() | {'startup_timeout': 2}
            )
        )


def test_playback_duration_starts_after_outputs_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = SimpleNamespace(now=0.0)

    def advance(seconds: float) -> None:
        clock.now += seconds

    def open_output() -> bool:
        advance(10)
        return True

    output = Mock(status=installation.StringStatus())
    output.open.side_effect = open_output
    active = Mock()
    active.name = 'across'
    active.render.return_value = [('left', np.zeros((1, 3), dtype=np.uint8))]
    service = installation.InstallationService.model_construct(
        config=installation_config.parse_installation(
            example_installation() | {'fps': 1}
        ),
        library=None,
        outputs={'left': output},
        home=tmp_path,
    )
    service.playback.active = active
    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(installation.time, 'sleep', advance)
    monkeypatch.setattr(installation.InstallationService, 'start', lambda self: None)
    monkeypatch.setattr(installation.InstallationService, 'close', lambda self: None)
    monkeypatch.setattr(
        installation_playback.InstallationPlayback, 'select', lambda self, name: None
    )

    assert service.run(duration=2) == 0
    assert output.send.call_count == 2
    assert clock.now == 12


def test_live_recording_uses_real_delivery_times_without_starting_test_devices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lyte import control_replay

    config = installation_config.parse_installation(
        example_installation() | {'fps': 2, 'midi': {}}
    )
    library = library_files.read_library(Path('examples/library.toml'))
    frames = []
    clock = SimpleNamespace(now=100.0)

    def sleep(seconds: float) -> None:
        clock.now += seconds

    outputs = {
        n: Mock(led_count=c, status=installation.StringStatus())
        for n, c in [('left', 2), ('right', 3)]
    }
    for output in outputs.values():
        output.open.return_value = True
        output.send.side_effect = lambda name, frame: (
            frames.append(frame.copy()) or True
        )
    service = installation.InstallationService.model_construct(
        config=config, library=library, outputs=outputs, home=tmp_path
    )
    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(installation.time, 'sleep', sleep)
    monkeypatch.setattr(installation, 'open_input', lambda config: Mock())
    monkeypatch.setattr(
        installation,
        'input_messages',
        lambda port, config: [mido.Message('note_on', note=60, velocity=100)],
    )
    monkeypatch.setattr(installation.InstallationService, 'start', lambda self: None)
    monkeypatch.setattr(installation.InstallationService, 'close', lambda self: None)
    destination = tmp_path / 'live.jsonl'
    assert service.run(duration=1, record_input=destination) == 0
    assert len(frames) == 4
    replay = control_replay.ControlReplay(destination)
    engine = installation_playback.InstallationPlayback(
        config, library, {'left': 2, 'right': 3}
    )
    engine.select('across')
    for index in range(2):
        at = replay.apply(engine)
        assert at == 100 + index / 2
        actual = engine.render(at)
        for (_, frame), expected in zip(
            actual, frames[index * 2 : index * 2 + 2], strict=True
        ):
            np.testing.assert_array_equal(frame, expected)
        replay.advance()
    assert replay.next_delivery is None
    replay.stream.close()


def test_render_failure_does_not_end_the_delivery_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = SimpleNamespace(now=0.0)

    def advance(seconds: float) -> None:
        clock.now += seconds

    output = Mock(led_count=2, status=installation.StringStatus())
    output.open.return_value = True
    active = Mock(name='active')
    active.name = 'across'
    frame = np.zeros((2, 3), dtype=np.uint8)
    active.render.side_effect = [ValueError('bad frame'), [('left', frame)]]
    service = installation.InstallationService.model_construct(
        config=installation_config.parse_installation(
            example_installation() | {'fps': 1}
        ),
        library=None,
        outputs={'left': output},
        home=tmp_path,
    )
    service.playback.active = active
    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(installation.time, 'sleep', advance)
    monkeypatch.setattr(installation.InstallationService, 'start', lambda self: None)
    monkeypatch.setattr(installation.InstallationService, 'close', lambda self: None)
    monkeypatch.setattr(
        installation_playback.InstallationPlayback, 'select', lambda self, name: None
    )
    assert service.run(duration=2) == 0
    output.send.assert_called_once()
    assert service.status_snapshot().render_error is None


def test_status_write_failure_does_not_break_operator_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = installation.InstallationService.model_construct(
        config=installation_config.parse_installation(example_installation()),
        library=None,
        outputs={},
        home=tmp_path,
    )

    def failed_status(self: object) -> None:
        raise ReccyError('disk full')

    monkeypatch.setattr(Reccy, 'publish_status', failed_status)
    assert service.rpc_response(rpc.Request(command='blackout')) == 'ok'
    assert service.status_snapshot().status_error == 'disk full'
    assert service.status_snapshot().blackout


def test_service_queues_animation_selection(tmp_path: Path) -> None:
    service = installation.InstallationService.model_construct(
        config=installation_config.parse_installation(example_installation()),
        library=None,
        outputs={},
        home=tmp_path,
    )

    response = service.rpc_response(
        rpc.Request(command='select_animation', params={'name': 'separate'})
    )

    assert response == {'state': 'queued', 'name': 'separate'}
    status = service.rpc_response(rpc.Request(command='status'))
    assert isinstance(status, dict)
    assert status['queued_animation'] == 'separate'
    assert status['animations'] == ['across', 'separate']
    assert not isinstance(response, ipc.Error)

    test = service.rpc_response(
        rpc.Request(command='test', params={'level': 30, 'duration': 1})
    )
    stop = service.rpc_response(rpc.Request(command='stop'))

    assert test == {'state': 'queued', 'level': 30.0, 'duration': 1.0}
    assert stop == 'ok'
    assert service._stop_requested.is_set()


def test_installation_service_uses_shared_lyte_identity(tmp_path: Path) -> None:
    service = installation.InstallationService.model_construct(home=tmp_path)

    assert service.name == 'lyte'
    assert service.control_endpoint == tmp_path / '.local/state/lyte/gui.sock'


def test_service_maps_midi_into_the_active_animation(tmp_path: Path) -> None:
    class Active:
        name = 'across'

        def __init__(self) -> None:
            self.calls: list[tuple[runtime_control.MidiPerformance, bool]] = []

        def apply_performance(
            self,
            performance: runtime_control.MidiPerformance,
            *,
            restart: bool = False,
        ) -> None:
            self.calls.append((performance.model_copy(deep=True), restart))

    active = Active()
    service = installation.InstallationService.model_construct(
        config=installation_config.parse_installation(
            example_installation()
            | {
                'midi': {'channel': 1},
                'animations': {
                    'across': {
                        'selector': 'examples:/composition.toml',
                        'outputs': {'light': 'left + right'},
                        'activation': 'note',
                    },
                    'separate': {
                        'selector': 'examples:/composition.toml',
                        'outputs': {'light': 'left * right'},
                    },
                },
            }
        ),
        library=None,
        outputs={},
        home=tmp_path,
    )
    service.playback.active = active

    service.playback.receive_midi(mido.Message('note_on', note=64, velocity=96))
    service.playback.receive_midi(mido.Message('control_change', control=2, value=80))
    service.playback.receive_midi(mido.Message('pitchwheel', pitch=-4096))

    status = service.status_snapshot()
    assert status.note == 64
    assert status.breath == 80
    assert status.pitch_bend == -4096
    assert [restart for _, restart in active.calls] == [True, False, False]


def test_installation_command_installs_reccy_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Service:
        argv: list[str] | None = None

        @classmethod
        def model_construct(cls) -> Service:
            return cls()

        def install_service(self, argv: list[str]) -> StatusResult:
            self.argv = argv
            return StatusResult(installed=True, running=True)

    service = Service()
    monkeypatch.setattr(
        installation.InstallationService,
        'model_construct',
        lambda: service,
    )
    monkeypatch.setattr(
        installation.controller, 'print_service_status', lambda name, result: None
    )

    result = installation.run_installation_command(
        installation.InstallationCommandConfig(
            action='install', config=tmp_path / 'installation.toml'
        )
    )

    assert result == 0
    assert service.argv == [
        'installation',
        'run',
        str((tmp_path / 'installation.toml').resolve()),
    ]


def discovered(host: str, **values: object) -> installation.DiscoveredTwinkly:
    return installation.DiscoveredTwinkly(
        host=host,
        device=diagnostic.TwinklyDeviceInfo(raw=values, **values),
    )


class CountingPrepared:
    def __init__(self) -> None:
        self.render_count = 0
        self.parameters: dict[str, float] = {}
        self.rate = Fraction(20)
        self.tick = 0
        self.timing = metrics.RenderCost(fps=20, light_count=2)

    def byte_frame(self, wired: bool) -> NDArray[np.uint8]:
        assert wired
        self.render_count += 1
        self.tick += 1
        return np.array([[0, 0, 0], [255, 0, 0]], dtype=np.uint8)

    def set_parameters(self, values: dict[str, float]) -> None:
        self.parameters = values


def example_installation() -> dict[str, object]:
    return {
        'library_config': 'examples/library.toml',
        'twinkly': {
            'left': {'product_name': 'Dots'},
            'right': {},
        },
        'animations': {
            'across': {
                'selector': 'examples:/composition.toml',
                'outputs': {'light': 'left + right'},
            },
            'separate': {
                'selector': 'examples:/composition.toml',
                'outputs': {'light': 'left * right'},
            },
        },
        'initial_animation': 'across',
    }


@pytest.fixture
def playback_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> installation.InstallationService:
    config = installation_config.parse_installation(
        example_installation() | {'midi': {}}
    )
    library = library_files.read_library(Path('examples/library.toml'))
    outputs = {
        'left': Mock(led_count=2, status=installation.StringStatus()),
        'right': Mock(led_count=3, status=installation.StringStatus()),
    }
    service = installation.InstallationService.model_construct(
        config=config, library=library, outputs=outputs, home=tmp_path
    )
    monkeypatch.setattr(
        installation.InstallationService, 'publish_status', lambda self: None
    )
    service.rpc_response(
        rpc.Request(command='select_animation', params={'name': 'across'})
    )
    service.render(0)
    return service


def test_light_test_resumes_the_selected_animation(
    playback_service: installation.InstallationService,
) -> None:
    service = playback_service
    expected = installation_playback.ActiveAnimation(
        'across',
        service.config.animations['across'],
        service.library,
        service.playback.led_counts,
    )
    expected.render(0)
    service.rpc_response(rpc.Request(command='test', params={'duration': 2}))
    service.render(1)
    assert service.render(2)[0][1][0, 0] == 128
    assert service.status_snapshot().active_test is not None
    frames = service.render(3.1)
    np.testing.assert_array_equal(frames[0][1], expected.render(3.1)[0][1])
    assert service.status_snapshot().active_test is None
    assert service.status_snapshot().active_animation == 'across'
    assert not service._stop_requested.is_set()


def test_blackout_cancels_tests_and_waits_for_selection(
    playback_service: installation.InstallationService,
) -> None:
    service = playback_service
    service.rpc_response(rpc.Request(command='test'))
    service.render(1)
    service.rpc_response(
        rpc.Request(command='select_animation', params={'name': 'separate'})
    )
    service.rpc_response(rpc.Request(command='blackout'))
    status = service.status_snapshot()
    assert status.blackout
    assert status.active_test is None
    assert status.queued_animation is None
    assert not any(f.any() for _, f in service.render(2))
    assert isinstance(service.rpc_response(rpc.Request(command='test')), ipc.Error)
    assert not any(f.any() for _, f in service.render(10))
    assert not service._stop_requested.is_set()
    service.rpc_response(
        rpc.Request(command='select_animation', params={'name': 'separate'})
    )
    service.render(11)
    assert not service.status_snapshot().blackout
    assert service.status_snapshot().active_animation == 'separate'
    service.rpc_response(rpc.Request(command='stop'))
    assert service._stop_requested.is_set()


def test_program_changes_each_advance_the_queued_selection(
    playback_service: installation.InstallationService,
) -> None:
    service = playback_service
    service.playback.receive_midi(mido.Message('program_change', program=70))
    assert service.status_snapshot().queued_animation == 'separate'
    service.playback.receive_midi(mido.Message('program_change', program=3))
    assert service.status_snapshot().queued_animation == 'across'
    service.render(1)
    assert service.status_snapshot().active_animation == 'across'
    assert service.status_snapshot().queued_animation is None

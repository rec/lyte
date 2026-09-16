from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import mido
import numpy as np
import pytest
from numpy.typing import NDArray
from pydantic import ValidationError
from reccy.protocol import ipc, rpc
from reccy.services.models import StatusResult
from ufor import library_files

from lyte import installation, runtime_control, show
from lyte.twinkly import diagnostic


def test_parse_installation_accepts_selectable_animations() -> None:
    config = installation.parse_installation(example_installation())

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
        installation.parse_installation(data)


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

    config = installation.parse_installation(data)

    assert config.animations['across'].activation == 'note'
    assert config.animations['across'].controls[0].parameter == 'brightness'
    assert config.animations['separate'].activation == 'always'
    assert config.animations['separate'].controls == []


def test_midi_controls_map_canonical_and_table_values() -> None:
    performance = runtime_control.MidiPerformance(note=61, velocity=64, breath=32)

    velocity = installation.ParameterControl(
        source='velocity', parameter='gain', output=[0.0, 2.0]
    )
    note = installation.ParameterControl(
        source='note', parameter='red', values=[0.25, 0.75]
    )

    assert velocity.map(performance) == pytest.approx(128 / 127)
    assert note.map(performance) == 0.75


def test_example_installation_is_valid() -> None:
    config = installation.load_installation(Path('examples/installation.toml'))

    assert config.initial_animation == 'tree_show'


def test_showco_installation_is_valid() -> None:
    config = installation.load_installation(Path('patches/showco-installation.toml'))

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
        installation.parse_installation(data)


def test_installation_rejects_missing_string_binding() -> None:
    data = example_installation()
    animations = data['animations']
    assert isinstance(animations, dict)
    across = animations['across']
    assert isinstance(across, dict)
    across['outputs'] = {'light': 'left'}

    with pytest.raises(ValueError, match="does not bind string 'right'"):
        installation.parse_installation(data)


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
        installation.parse_output_expression(value, {'left', 'right', 'back'})


def test_concatenated_output_scales_then_partitions() -> None:
    source = np.array([[0, 0, 0], [100, 0, 0], [200, 0, 0]], dtype=np.uint8)
    expression = installation.parse_output_expression('left + right', {'left', 'right'})

    frames = installation.distribute_frame(source, expression, {'left': 2, 'right': 3})

    assert [name for name, _ in frames] == ['left', 'right']
    assert frames[0][1].tolist() == [[0, 0, 0], [0, 0, 0]]
    assert frames[1][1].tolist() == [[100, 0, 0], [100, 0, 0], [200, 0, 0]]


def test_mirrored_output_scales_each_copy() -> None:
    source = np.array([[0, 0, 0], [255, 0, 0]], dtype=np.uint8)
    expression = installation.parse_output_expression('left * right', {'left', 'right'})

    frames = installation.distribute_frame(source, expression, {'left': 3, 'right': 5})

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
    active = object.__new__(installation.ActiveAnimation)
    active.outputs = {
        'left': Output(led_count=2),
        'right': Output(led_count=3),
    }
    active.definition = installation.BoundAnimation(
        selector='examples:/composition.toml',
        outputs={'light': 'left * right'},
    )
    active.performance = runtime_control.MidiPerformance()
    active.started_at = None
    active.bindings = [
        installation.PreparedBinding(
            output_name='light',
            expression=installation.parse_output_expression(
                'left * right', active.outputs
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
    active = installation.ActiveAnimation(
        'aurora',
        installation.BoundAnimation(selector='aurora', outputs={'light': 'left'}),
        library,
        {'left': Output(led_count=250)},
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
    active = installation.ActiveAnimation(
        'aurora',
        installation.BoundAnimation(
            selector='aurora', outputs={'light': 'left'}, activation='note'
        ),
        library,
        {'left': Output(led_count=250)},
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
    active = object.__new__(installation.ActiveAnimation)
    active.definition = installation.BoundAnimation(
        selector='examples:/composition.toml',
        outputs={'light': 'left'},
        controls=[
            installation.ParameterControl(
                source='breath', parameter='brightness', output=[0.0, 2.0]
            )
        ],
    )
    active.bindings = [
        installation.PreparedBinding(
            output_name='light',
            expression=installation.OutputExpression(['left'], 'single'),
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
            'left': installation.TwinklySelector(product_name='dots'),
            'right': installation.TwinklySelector(),
        },
        [dots, strings],
    )

    assert assignment == {'left': dots, 'right': strings}


def test_assignment_rejects_indistinguishable_devices() -> None:
    devices = [
        discovered('192.168.1.10', product_name='Twinkly Dots'),
        discovered('192.168.1.11', product_name='Twinkly Dots'),
    ]

    with pytest.raises(installation.InstallationFileError, match='ambiguous'):
        installation.assign_twinkly_devices(
            {
                'left': installation.TwinklySelector(),
                'right': installation.TwinklySelector(),
            },
            devices,
        )


def test_service_queues_animation_selection(tmp_path: Path) -> None:
    service = installation.InstallationService.model_construct(
        config=installation.parse_installation(example_installation()),
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
        config=installation.parse_installation(
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
    service._active = active

    service._receive_midi(mido.Message('note_on', note=64, velocity=96))
    service._receive_midi(mido.Message('control_change', control=2, value=80))
    service._receive_midi(mido.Message('pitchwheel', pitch=-4096))

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


class Output:
    def __init__(self, led_count: int) -> None:
        self.led_count = led_count


class CountingPrepared:
    def __init__(self) -> None:
        self.render_count = 0
        self.parameters: dict[str, float] = {}
        self.rate = Fraction(20)
        self.tick = 0

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

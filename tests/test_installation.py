from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from pydantic import ValidationError
from reccy.protocol import ipc, rpc

from lyte import installation
from lyte.twinkly import diagnostic


def test_parse_installation_accepts_selectable_animations() -> None:
    config = installation.parse_installation(example_installation())

    assert config.twinkly['left'].product_name == 'Dots'
    assert config.animations['across'].outputs == {'light': 'left + right'}
    assert config.initial_animation == 'across'


def test_example_installation_is_valid() -> None:
    config = installation.load_installation(Path('examples/installation.toml'))

    assert config.initial_animation == 'tree_show'


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
    active.bindings = [
        installation.PreparedBinding(
            output_name='light',
            expression=installation.parse_output_expression(
                'left * right', active.outputs
            ),
            prepared=prepared,
        )
    ]

    frames = active.render()

    assert prepared.render_count == 1
    assert [frame.shape for _, frame in frames] == [(2, 3), (3, 3)]


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

    def byte_frame(self, wired: bool) -> NDArray[np.uint8]:
        assert wired
        self.render_count += 1
        return np.array([[0, 0, 0], [255, 0, 0]], dtype=np.uint8)


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

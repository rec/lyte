from __future__ import annotations

from collections import deque
from pathlib import Path
from unittest.mock import patch

import mido
from pydantic import BaseModel
from reccy import rpc
from reccy.reccy import Reccy

from lyte import daemon_config, daemon_runtime, midi, patches


def test_reccy_daemon_handles_commands(tmp_path: Path) -> None:
    project = daemon_config.DaemonProject(
        config=daemon_config.DaemonConfig(
            patch_library=Path('patches/wearable-breath.toml'),
            patches=['one', 'two'],
            midi=midi.MidiIn(channel=1),
            twinkly=daemon_config.TwinklyDaemonConfig(),
        ),
        library=object(),
    )
    daemon = daemon_runtime.LyteMidiDaemon(project=project, home=tmp_path)

    status = daemon.rpc_response(rpc.Request(command='status'))
    select = daemon.rpc_response(
        rpc.Request(command='select_patch', params={'name': 'two'})
    )
    blackout = daemon.rpc_response(rpc.Request(command='blackout'))

    assert isinstance(daemon, Reccy)
    assert isinstance(status, dict)
    assert status['patch'] == 'one'
    assert select == {'state': 'queued', 'generation': 1}
    assert daemon._selected_patch == ('two', 1)
    assert status['selection_generation'] == 0
    assert status['applied_selection_generation'] == 0
    assert blackout == 'ok'
    assert daemon.status_snapshot().state == 'stopping'

    with patch('reccy.reccy.rpc.Server'):
        daemon.start()
        try:
            saved = daemon_runtime.LyteMidiStatus.model_validate_json(
                daemon.status_path.read_text()
            )
            assert saved.running
            assert saved.patch == 'one'
        finally:
            daemon.close()


def test_daemon_rate_limits_repeated_render_errors(tmp_path: Path) -> None:
    project = daemon_config.DaemonProject(
        config=daemon_config.DaemonConfig(
            patch_library=Path('patches/wearable-breath.toml'),
            patches=['one'],
            midi=midi.MidiIn(channel=1),
            twinkly=daemon_config.TwinklyDaemonConfig(),
        ),
        library=object(),
    )
    daemon = daemon_runtime.LyteMidiDaemon(project=project, home=tmp_path)

    with patch.object(daemon_runtime.LyteMidiDaemon, 'publish_error') as publish_error:
        daemon._record_render_error('one', ValueError('invalid frame'))
        daemon._record_render_error('one', ValueError('invalid frame'))

    status = daemon.status_snapshot()
    assert publish_error.call_count == 1
    assert status.render_error == 'Patch one render failed: invalid frame'
    assert status.render_error_count == 2
    assert status.last_failure == 'Patch one render failed: invalid frame'
    assert status.failure_count == 2

    daemon._clear_render_error()

    status = daemon.status_snapshot()
    assert status.render_error is None
    assert status.render_error_count == 0


class Config(BaseModel, frozen=True):
    pass


class State(BaseModel):
    pass


class RecordingPatch(midi.LightPatch[Config, State]):
    events: list[str] = []

    def make_state(self, msg: mido.Message) -> State:
        self.events.append(f'note:{msg.note}:{msg.velocity}')
        return State()

    def breath_control(self, msg: mido.Message) -> None:
        self.events.append(f'breath:{msg.value}')

    def pitch_bend(self, msg: mido.Message) -> None:
        self.events.append(f'pitch:{msg.pitch}')

    def program_change(self, msg: mido.Message) -> None:
        self.events.append(f'program:{msg.program}')

    def render(self, device: object) -> object:
        raise NotImplementedError


def test_program_change_wraps_to_the_first_patch(monkeypatch: object) -> None:
    created: deque[RecordingPatch] = deque()

    def build_patch(library: object, name: str) -> RecordingPatch:
        patch = RecordingPatch(config=Config())
        created.append(patch)
        return patch

    monkeypatch.setattr(daemon_runtime.patches, 'build_light_patch', build_patch)
    selector = daemon_runtime.PatchSelector.create(object(), ['one', 'two'])

    selector.receive(mido.Message('program_change', program=3))
    selector.receive(mido.Message('program_change', program=4))

    assert selector.patch_name == 'one'
    assert list(created)[0].events == ['program:3']


def test_program_change_replays_active_note_controls(monkeypatch: object) -> None:
    created: list[RecordingPatch] = []

    def build_patch(library: object, name: str) -> RecordingPatch:
        patch = RecordingPatch(config=Config())
        created.append(patch)
        return patch

    monkeypatch.setattr(daemon_runtime.patches, 'build_light_patch', build_patch)
    selector = daemon_runtime.PatchSelector.create(object(), ['one', 'two'])
    selector.receive(mido.Message('note_on', channel=2, note=60, velocity=100))
    selector.receive(mido.Message('control_change', channel=2, control=2, value=64))
    selector.receive(mido.Message('pitchwheel', channel=2, pitch=1024))
    selector.receive(mido.Message('program_change', channel=2, program=1))

    assert selector.patch_name == 'two'
    assert created[1].events == ['note:60:100', 'breath:64', 'pitch:1024']


def test_midi_disconnect_ends_the_active_patch(monkeypatch: object) -> None:
    created: list[RecordingPatch] = []

    def build_patch(library: object, name: str) -> RecordingPatch:
        patch = RecordingPatch(config=Config())
        created.append(patch)
        return patch

    monkeypatch.setattr(daemon_runtime.patches, 'build_light_patch', build_patch)
    selector = daemon_runtime.PatchSelector.create(object(), ['one'])
    selector.receive(mido.Message('note_on', channel=2, note=60, velocity=100))

    selector.clear_performance()

    assert selector.performance.note is None
    assert created[0].state is None


def test_daemon_reopens_an_unavailable_midi_input(tmp_path: Path) -> None:
    class Port:
        closed = False

        def close(self) -> None:
            self.closed = True

        def poll(self) -> mido.Message | None:
            return None

    class FakeTrack:
        def __init__(self, **kwargs: object) -> None:
            self.device = kwargs['device']

        def prepare(self) -> bool:
            return True

        def stream_frames(
            self,
            name: str,
            fps: float,
            duration: float | None,
            render_frame: object,
            before_frame: object,
        ) -> None:
            before_frame()
            before_frame()

        def close(self) -> None:
            pass

    library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
    project = daemon_config.DaemonProject(
        config=daemon_config.DaemonConfig(
            patch_library=Path('patches/wearable-breath.toml'),
            patches=['breath_walker'],
            midi=midi.MidiIn(channel=1),
            twinkly=daemon_config.TwinklyDaemonConfig(host='192.168.1.23'),
        ),
        library=library,
    )
    port = Port()
    with (
        patch(
            'lyte.daemon_runtime.realtime.recover_streaming_device',
            return_value='192.168.1.23',
        ),
        patch('lyte.daemon_runtime.realtime.prepare_device', return_value=True),
        patch(
            'lyte.daemon_runtime.realtime.turn_off_streaming_device', return_value=True
        ),
        patch(
            'lyte.daemon_runtime.midi.open_input',
            side_effect=[ValueError('missing'), port],
        ) as open_input,
        patch('lyte.daemon_runtime.track.TwinklyTrack', FakeTrack),
        patch.object(daemon_runtime.LyteMidiDaemon, 'start'),
        patch.object(daemon_runtime.LyteMidiDaemon, 'close'),
        patch(
            'lyte.daemon_runtime.time.monotonic', side_effect=[0.0, 0.0, 1.0, 1.0, 1.0]
        ),
    ):
        result = daemon_runtime.LyteMidiDaemon(project=project, home=tmp_path).run()

    assert result == 0
    assert open_input.call_count == 2
    assert port.closed

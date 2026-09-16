"""Read and replay a control journal without starting physical outputs."""

import json
from pathlib import Path

import mido
from reccy.protocol import ipc
from ufor.events import MidiEvent

from .control_recording import Delivery, RecordingHeader
from .installation_playback import InstallationPlayback
from .preview.document import preview_frame_count


class ControlReplay:
    def __init__(self, path: Path) -> None:
        self.stream = path.open()
        try:
            self.header = RecordingHeader.model_validate_json(self.stream.readline())
            self.next_delivery: Delivery | None = None
            self.previous_time: float | None = None
            self.advance()
        except (ValueError, OSError):
            self.stream.close()
            raise

    def advance(self) -> None:
        line = self.stream.readline()
        if not line:
            raise ValueError('control recording is incomplete: missing end marker')
        if json.loads(line) == {'kind': 'end'}:
            self.next_delivery = None
            return
        delivery = Delivery.model_validate_json(line)
        if self.previous_time is not None and delivery.at < self.previous_time:
            raise ValueError('recorded delivery times must not go backwards')
        self.previous_time = delivery.at
        self.next_delivery = delivery

    def apply(self, playback: InstallationPlayback) -> float | None:
        delivery = self.next_delivery
        if delivery is None:
            return None
        if set(delivery.string_counts) != set(playback.led_counts):
            raise ValueError('recorded strings differ from this installation')
        preview_frame_count(1, 1, sum(delivery.string_counts.values()) * 3)
        playback.led_counts.update(delivery.string_counts)
        for event in delivery.inputs:
            if isinstance(event, MidiEvent):
                playback.receive_midi(mido.Message.from_bytes(event.data))
            elif event.command == 'reset_midi':
                playback.reset_midi()
            else:
                result = playback.command(event.command, event.params)
                if isinstance(result, ipc.Error):
                    raise ValueError(result.message)
        return delivery.at

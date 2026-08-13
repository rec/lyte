from __future__ import annotations

from lyte import daemon


def test_midi_daemon_service_has_a_stable_identity() -> None:
    assert daemon.LYTE_MIDI_SERVICE.name == 'lyte-midi'
    assert daemon.LYTE_MIDI_SERVICE.launchd_label == 'com.swirly.lyte-midi'
    assert daemon.LYTE_MIDI_SERVICE.daemon_env_var == 'LYTE_MIDI_DAEMON'

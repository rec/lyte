"""Background-service definition for the Lyte MIDI daemon."""

from reccy.models import ServiceSpec

LYTE_MIDI_SERVICE = ServiceSpec(
    name='lyte-midi',
    display_name='Lyte MIDI',
    description='Lyte MIDI patch player',
    launchd_label='com.swirly.lyte-midi',
    daemon_env_var='LYTE_MIDI_DAEMON',
    windows_pipe=r'\.\pipe\lyte-midi',
)

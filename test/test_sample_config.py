from typing import TYPE_CHECKING

from pydantic import Field

from lyte.installation_config import BoundAnimation, InstallationFile, TwinklySelector
from lyte.midi import MidiIn
from lyte.schedule import DailySchedule

if TYPE_CHECKING:
    from reccy.pytest_plugin import SampleConfigRegression


class ExampleInstallation(InstallationFile, frozen=True):
    schedule: DailySchedule | None = DailySchedule(
        latitude=49.44, longitude=1.10, timezone='Europe/Paris'
    )
    twinkly: dict[str, TwinklySelector] = {
        'front': TwinklySelector(device_name='Example lights')
    }
    animations: dict[str, BoundAnimation] = Field(
        default={
            'wash': BoundAnimation(selector='demo:wash', outputs={'light': 'front'})
        },
        min_length=1,
    )
    initial_animation: str = 'wash'
    midi: MidiIn | None = MidiIn(channel=1, device_name='Example keyboard')


def test_sample_config(sample_config_regression: 'SampleConfigRegression') -> None:
    sample_config_regression(ExampleInstallation)

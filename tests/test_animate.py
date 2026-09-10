from pathlib import Path

import pytest

from lyte.animate import config, playback


def test_parse_args_selects_ufor_score() -> None:
    result = playback.parse_args(
        [
            'examples:/composition.toml',
            '--library-config',
            'examples/library.toml',
            '--duration',
            '2',
            '--parameters',
            'brightness',
            '0.5',
        ]
    )

    assert result.selector == 'examples:/composition.toml'
    assert result.library_config == Path('examples/library.toml')
    assert result.duration == 2
    assert result.parameters == {'brightness': 0.5}


@pytest.mark.parametrize(
    ('args', 'message'),
    [
        (config.AnimateConfig(selector='score', attempts=0), 'attempts'),
        (config.AnimateConfig(selector='score', retry_delay=-1), 'retry-delay'),
        (config.AnimateConfig(selector='score', retry_backoff=0.5), 'retry-backoff'),
        (config.AnimateConfig(selector='score', duration=0), 'duration'),
    ],
)
def test_validate_args_rejects_invalid_host_settings(
    args: config.AnimateConfig, message: str
) -> None:
    with pytest.raises(SystemExit, match=message):
        config.validate_args(args)

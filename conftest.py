import pytest

pytest_plugins = ['reccy.pytest_plugin']


def pytest_configure(config: pytest.Config) -> None:
    workers = config.getoption('numprocesses')
    if config.getoption('force_regen') and workers not in (None, 0, '0'):
        raise pytest.UsageError(
            'CLI-help fixture regeneration must be serial: use pytest -n 0 '
            '--force-regen'
        )

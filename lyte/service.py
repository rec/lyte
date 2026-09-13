"""Shared Lyte service identity."""

from pathlib import Path

from reccy.services import spec

LYTE_SERVICE = spec.load(Path(__file__).with_name('service.toml'))

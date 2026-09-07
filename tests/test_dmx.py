from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from lyte import dmx


def test_instrument_encodes_semantic_categories() -> None:
    instrument = example_instrument()
    values = dmx.DmxValues(
        brightness=0.5,
        rgb=[1.0, 0.25, 0.0],
        chase_speed=1.0,
        pattern='chase',
    )

    slots = dmx.encode_instrument(
        np.zeros(dmx.DMX_CHANNEL_COUNT, dtype=np.uint8), instrument, values
    )

    assert slots[:8].tolist() == [128, 255, 64, 0, 255, 64, 0, 0]
    assert np.all(slots[8:] == 0)


def test_multiple_instruments_share_a_universe() -> None:
    first = example_instrument()
    second = first.model_copy(update={'name': 'rear', 'start_channel': 9})

    frames = dmx.render_universes(
        [
            dmx.InstrumentOutput(
                instrument=first, values=dmx.DmxValues(brightness=1.0)
            ),
            dmx.InstrumentOutput(
                instrument=second, values=dmx.DmxValues(rgb=[0.0, 1.0, 0.0])
            ),
        ]
    )

    assert list(frames) == [1]
    assert frames[1].slots[0] == 255
    assert frames[1].slots[10] == 255


def test_instrument_rejects_channel_range_overflow() -> None:
    with pytest.raises(ValidationError, match='end at or before 512'):
        example_instrument().model_copy(
            update={'start_channel': 510, 'channel_count': 8}
        ).model_validate(
            example_instrument().model_dump()
            | {'start_channel': 510, 'channel_count': 8}
        )


def test_instrument_rejects_empty_channel_collection() -> None:
    with pytest.raises(ValidationError, match='at least 1 item'):
        dmx.DmxInstrument(
            name='wash',
            universe=1,
            start_channel=1,
            channel_count=1,
            categories=[{'kind': 'brightness', 'channels': []}],
        )


def test_instrument_rejects_duplicate_category_channels() -> None:
    with pytest.raises(ValidationError, match='assigned to both'):
        dmx.DmxInstrument(
            name='wash',
            universe=1,
            start_channel=1,
            channel_count=2,
            categories=[
                {'kind': 'brightness', 'channels': [1]},
                {'kind': 'strobe', 'channels': [1]},
            ],
        )


def test_pattern_value_must_fit_its_channels() -> None:
    with pytest.raises(ValidationError, match='does not fit'):
        dmx.PatternSelectChannels(channels=[1], patterns={'invalid': 256})


def test_unknown_pattern_fails_during_encoding() -> None:
    with pytest.raises(ValueError, match="unknown pattern 'missing'"):
        dmx.encode_instrument(
            np.zeros(dmx.DMX_CHANNEL_COUNT, dtype=np.uint8),
            example_instrument(),
            dmx.DmxValues(pattern='missing'),
        )


def test_overlapping_instruments_are_rejected() -> None:
    instrument = example_instrument()
    with pytest.raises(ValueError, match='overlaps universe 1 channel 8'):
        dmx.render_universes(
            [
                dmx.InstrumentOutput(instrument=instrument, values=dmx.DmxValues()),
                dmx.InstrumentOutput(
                    instrument=instrument.model_copy(
                        update={'name': 'overlap', 'start_channel': 8}
                    ),
                    values=dmx.DmxValues(),
                ),
            ]
        )


def test_static_program_keeps_state_per_instrument() -> None:
    instrument = example_instrument()
    program = dmx.StaticDmxProgram(values=dmx.DmxValues(brightness=0.75))
    state = program.initial_state(instrument)

    assert program.render(instrument, state).brightness == 0.75
    assert state.frame == 1


def example_instrument() -> dmx.DmxInstrument:
    return dmx.DmxInstrument(
        name='front',
        universe=1,
        start_channel=1,
        channel_count=8,
        categories=[
            dmx.BrightnessChannels(channels=[1]),
            dmx.RgbChannels(red=[2], green=[3], blue=[4]),
            dmx.ChaseSpeedChannels(channels=[5]),
            dmx.PatternSelectChannels(
                channels=[6], patterns={'static': 0, 'chase': 64}
            ),
            dmx.RawChannels(name='reserved', channels=[7, 8]),
        ],
    )

from __future__ import annotations

import base64
import wave
from fractions import Fraction
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest
from pytest_regressions.data_regression import DataRegressionFixture
from ufor import codec, library_files
from ufor.light_animation import AnimationScore

from lyte import authoring, render, show
from lyte.audio_input import AudioAnalysis
from lyte.preview.document import encoded_frames


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    # More than one second at 48 kHz, ending partway through a score frame.
    t = np.arange(48_123, dtype=np.float64) / 48_000
    left = 0.6 * np.sin(2 * np.pi * 100 * t)
    right = 0.3 * np.sin(2 * np.pi * 2500 * t)
    samples = np.column_stack([left, right])
    path = tmp_path / 'source.wav'
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((2, 2, 48_000, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.round(samples * 32767).astype('<i2').tobytes())
    return path


def test_audio_editor_html_and_movie_frames_match_through_eof(
    audio_file: Path, tmp_path: Path, data_regression: DataRegressionFixture
) -> None:
    config = Path('examples/audio/library.toml')
    library = library_files.read_library(config)
    prepared = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='spectrum')
    )
    with pytest.raises(ValueError, match='requires --audio'):
        prepared.render()
    prepared.set_audio(audio_file)
    html_frames = [base64.b64decode(f) for f in encoded_frames(prepared, 0.1)]
    # Duration is the audio extent, including a padded final frame, not --duration.
    assert len(html_frames) == 31
    with pytest.raises(ValueError, match='EOF'):
        prepared.render()
    session = authoring.AuthoringSession(
        library, authoring.AuthorConfig(audio=audio_file, duration=0.1)
    )
    editor = session.preview('audio:/spectrum.toml', {})
    assert editor['audio'] is True
    assert [base64.b64decode(f) for f in editor['frames']] == html_frames
    process = Mock()
    process.stdin.closed = False
    process.wait.return_value = 0

    def start(command: list[str], stdin: object) -> Mock:
        assert command[command.index('-framerate') + 1] == '30000/1001'
        assert float(command[command.index('-t') + 1]) == 48123 / 48000
        Path(command[-1]).write_bytes(b'movie')
        return process

    with (
        patch.object(render.subprocess, 'Popen', side_effect=start),
        patch.object(render.FrameRenderer, 'render', side_effect=lambda x: x),
    ):
        render.render_animation(
            'spectrum',
            render.RenderConfig(audio=audio_file, output=tmp_path, duration=0.1),
            'ffmpeg',
            library,
        )
    assert [c.args[0] for c in process.stdin.write.call_args_list] == html_frames
    data_regression.check({'frames': [list(f) for f in html_frames]})


def test_audio_limits_and_truncation_do_not_render_partial_results(
    audio_file: Path,
) -> None:
    with pytest.raises(ValueError, match='preview exceeds'):
        AudioAnalysis(audio_file, Fraction(30), max_frames=1)
    audio_file.write_bytes(audio_file.read_bytes()[:-4])
    with pytest.raises(ValueError, match='declared sample count'):
        AudioAnalysis(audio_file, Fraction(30))


@pytest.mark.parametrize('width', [1, 2, 3, 4])
def test_pcm_widths_and_final_padding(
    tmp_path: Path, width: int, data_regression: DataRegressionFixture
) -> None:
    # Alternating signed half-scale for a second plus a final positive sample.
    sample = (192 if width == 1 else 2 ** (width * 8 - 2)).to_bytes(width, 'little')
    negative = (64 if width == 1 else -(2 ** (width * 8 - 2))).to_bytes(
        width, 'little', signed=width != 1
    )
    path = tmp_path / 'constant.wav'
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, width, 48_000, 0, 'NONE', 'not compressed'))
        stream.writeframes((sample + negative) * 24_000 + sample)
    analysis = AudioAnalysis(path, Fraction(30))
    data_regression.check(
        {
            'count': len(analysis.frames),
            'first_level': round(analysis.frames[0].level, 8),
            'last_level': round(analysis.frames[-1].level, 8),
        }
    )


def test_later_cues_use_the_root_audio_clock(audio_file: Path, tmp_path: Path) -> None:
    data = codec.parse_score(
        Path('examples/audio/spectrum.toml').read_text()
    ).model_dump(mode='json')
    data['body']['operation']['smoothing'] = 10000
    leaf = AnimationScore.model_validate(data)
    (tmp_path / 'spectrum.toml').write_text(codec.score_toml(leaf))
    data['name'] = 'cues'
    data['body']['parts'] = [
        {'name': n, 'score': {'path': 'spectrum.toml'}} for n in ['first', 'second']
    ]
    data['body']['operation'] = {
        'effect': 'cues',
        'cues': [
            {
                'source': {'part': 'first', 'output': 'light'},
                'start': '0',
                'duration': '1001/2000',
            },
            {
                'source': {'part': 'second', 'output': 'light'},
                'start': '1001/2000',
                'duration': '1001/1875',
            },
        ],
    }
    (tmp_path / 'cues.toml').write_text(
        codec.score_toml(AnimationScore.model_validate(data))
    )
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "audio"\nroot = "."\n')
    library = library_files.read_library(config)
    frames = []
    for selector in ['spectrum', 'cues']:
        prepared = show.prepare_library_animation(
            library, show.LightProgramSpec(selector=selector)
        )
        prepared.set_audio(audio_file)
        frames.append(encoded_frames(prepared, 0.1))
    assert frames[0] == frames[1]

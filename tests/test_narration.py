import base64
import json
from contextlib import asynccontextmanager

import pytest

from rokid_physical_ai import narration


@pytest.mark.parametrize(
    "spoken,accepted",
    [
        ("Перенести куб, в зону справа!", True),
        ("Перенести куб в зону слева.", False),
        ("Перенести куб в зону справа. Выполняю.", False),
        ("", False),
    ],
)
def test_narration_requires_the_same_words(spoken, accepted):
    assert narration.same_words("Перенести куб в зону справа.", spoken) is accepted


@pytest.mark.parametrize(
    "transcript,status,accepted",
    [
        ("Проверка связи.", "completed", True),
        ("Выполняю перенос.", "completed", False),
        ("Проверка связи.", "incomplete", False),
    ],
)
async def test_realtime_speech_is_withheld_until_verified(
    monkeypatch, transcript, status, accepted
):
    sent = []
    pcm = b"\x01\x02" * 100

    class Socket:
        async def send(self, data):
            sent.append(json.loads(data))

        async def __aiter__(self):
            for event in [
                {"type": "session.updated"},
                {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
                {"type": "response.output_audio_transcript.done", "transcript": transcript},
                {"type": "response.done", "response": {"status": status}},
            ]:
                yield json.dumps(event)

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield Socket()

    monkeypatch.setattr(narration, "connect", connect)
    if accepted:
        assert await narration.synthesize("test-credential", "Проверка связи.") == pcm
    else:
        with pytest.raises(ValueError, match="not_verbatim"):
            await narration.synthesize("test-credential", "Проверка связи.")
    assert sent[0]["session"]["tools"] == []
    assert sent[1]["response"]["conversation"] == "none"

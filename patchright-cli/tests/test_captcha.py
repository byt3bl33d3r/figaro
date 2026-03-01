"""Tests for patchright_cli.captcha module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from patchright_cli.captcha import find_audio_url, transcribe_audio


# ---------------------------------------------------------------------------
# find_audio_url
# ---------------------------------------------------------------------------


class TestFindAudioUrl:
    async def test_finds_audio_in_main_frame(self):
        frame = MagicMock()
        frame.evaluate = AsyncMock(return_value="https://example.com/audio.mp3")
        page = MagicMock()
        page.frames = [frame]

        result = await find_audio_url(page)
        assert result == "https://example.com/audio.mp3"
        frame.evaluate.assert_awaited_once_with(
            "document.querySelector('audio')?.src || ''"
        )

    async def test_finds_audio_in_second_frame(self):
        frame1 = MagicMock()
        frame1.evaluate = AsyncMock(return_value="")
        frame2 = MagicMock()
        frame2.evaluate = AsyncMock(return_value="https://example.com/captcha.wav")
        page = MagicMock()
        page.frames = [frame1, frame2]

        result = await find_audio_url(page)
        assert result == "https://example.com/captcha.wav"

    async def test_returns_none_when_no_audio(self):
        frame = MagicMock()
        frame.evaluate = AsyncMock(return_value="")
        page = MagicMock()
        page.frames = [frame]

        result = await find_audio_url(page)
        assert result is None

    async def test_returns_none_with_no_frames(self):
        page = MagicMock()
        page.frames = []

        result = await find_audio_url(page)
        assert result is None

    async def test_stops_at_first_audio_found(self):
        frame1 = MagicMock()
        frame1.evaluate = AsyncMock(return_value="https://first.com/audio.mp3")
        frame2 = MagicMock()
        frame2.evaluate = AsyncMock(return_value="https://second.com/audio.mp3")
        page = MagicMock()
        page.frames = [frame1, frame2]

        result = await find_audio_url(page)
        assert result == "https://first.com/audio.mp3"
        frame2.evaluate.assert_not_awaited()

    async def test_skips_empty_string_src(self):
        frame1 = MagicMock()
        frame1.evaluate = AsyncMock(return_value="")
        frame2 = MagicMock()
        frame2.evaluate = AsyncMock(return_value="")
        frame3 = MagicMock()
        frame3.evaluate = AsyncMock(return_value="https://audio.test/file.ogg")
        page = MagicMock()
        page.frames = [frame1, frame2, frame3]

        result = await find_audio_url(page)
        assert result == "https://audio.test/file.ogg"

    async def test_multiple_frames_all_empty(self):
        frames = [MagicMock() for _ in range(5)]
        for f in frames:
            f.evaluate = AsyncMock(return_value="")
        page = MagicMock()
        page.frames = frames

        result = await find_audio_url(page)
        assert result is None
        for f in frames:
            f.evaluate.assert_awaited_once()


# ---------------------------------------------------------------------------
# transcribe_audio
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    @patch("patchright_cli.captcha.AsyncOpenAI")
    async def test_returns_transcription_text(self, mock_openai_cls):
        mock_transcript = MagicMock()
        mock_transcript.text = "hello world"
        mock_client = MagicMock()
        mock_client.audio = MagicMock()
        mock_client.audio.transcriptions = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )
        mock_openai_cls.return_value = mock_client

        result = await transcribe_audio(b"fake-audio-data", "sk-test-key")
        assert result == "hello world"

    @patch("patchright_cli.captcha.AsyncOpenAI")
    async def test_passes_correct_model(self, mock_openai_cls):
        mock_transcript = MagicMock()
        mock_transcript.text = "test"
        mock_client = MagicMock()
        mock_client.audio = MagicMock()
        mock_client.audio.transcriptions = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )
        mock_openai_cls.return_value = mock_client

        await transcribe_audio(b"data", "sk-key")
        call_kwargs = mock_client.audio.transcriptions.create.call_args
        assert call_kwargs.kwargs["model"] == "whisper-1"

    @patch("patchright_cli.captcha.AsyncOpenAI")
    async def test_passes_api_key(self, mock_openai_cls):
        mock_transcript = MagicMock()
        mock_transcript.text = "text"
        mock_client = MagicMock()
        mock_client.audio = MagicMock()
        mock_client.audio.transcriptions = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )
        mock_openai_cls.return_value = mock_client

        await transcribe_audio(b"data", "sk-my-secret-key")
        mock_openai_cls.assert_called_once_with(api_key="sk-my-secret-key")

    @patch("patchright_cli.captcha.AsyncOpenAI")
    async def test_sends_audio_bytes_as_file_tuple(self, mock_openai_cls):
        mock_transcript = MagicMock()
        mock_transcript.text = "result"
        mock_client = MagicMock()
        mock_client.audio = MagicMock()
        mock_client.audio.transcriptions = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )
        mock_openai_cls.return_value = mock_client

        await transcribe_audio(b"\x00\x01\x02", "sk-key")
        call_kwargs = mock_client.audio.transcriptions.create.call_args
        file_arg = call_kwargs.kwargs["file"]
        assert file_arg[0] == "audio.wav"
        assert file_arg[1].read() == b"\x00\x01\x02"

    @patch("patchright_cli.captcha.AsyncOpenAI")
    async def test_empty_audio_data(self, mock_openai_cls):
        mock_transcript = MagicMock()
        mock_transcript.text = ""
        mock_client = MagicMock()
        mock_client.audio = MagicMock()
        mock_client.audio.transcriptions = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=mock_transcript
        )
        mock_openai_cls.return_value = mock_client

        result = await transcribe_audio(b"", "sk-key")
        assert result == ""

"""Tests for STT (speech-to-text) transcription module."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from figaro_gateway.stt import (
    TranscriptionError,
    _convert_to_pcm,
    _receive_transcript,
    _send_audio_chunks,
    load_oauth_token,
    transcribe_audio,
)


class AsyncIteratorMock:
    """Mock that supports async iteration over a list of items."""

    def __init__(self, items: list):
        self._items = iter(items)
        self.send = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class TestLoadOauthToken:
    """Tests for load_oauth_token — credential file reading."""

    def test_returns_token_when_present(self, tmp_path):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": "test-token-123"}}))

        token = load_oauth_token(creds_file)

        assert token == "test-token-123"

    def test_returns_none_when_file_missing(self, tmp_path):
        token = load_oauth_token(tmp_path / "nonexistent.json")

        assert token is None

    def test_returns_none_when_token_absent(self, tmp_path):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"claudeAiOauth": {}}))

        token = load_oauth_token(creds_file)

        assert token is None

    def test_returns_none_when_oauth_key_missing(self, tmp_path):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"other": "data"}))

        token = load_oauth_token(creds_file)

        assert token is None

    def test_returns_none_on_invalid_json(self, tmp_path):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text("not json")

        token = load_oauth_token(creds_file)

        assert token is None


class TestConvertToPcm:
    """Tests for _convert_to_pcm — ffmpeg audio conversion."""

    async def test_successful_conversion(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"pcm-data", b""))
        mock_proc.returncode = 0

        with patch("figaro_gateway.stt.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await _convert_to_pcm(b"ogg-data")

        assert result == b"pcm-data"
        mock_exec.assert_called_once()
        # Verify ffmpeg was called with correct args
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "ffmpeg"
        assert "pipe:0" in call_args
        assert "pipe:1" in call_args

    async def test_ffmpeg_failure_raises(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: invalid input"))
        mock_proc.returncode = 1

        with patch("figaro_gateway.stt.asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(TranscriptionError, match="ffmpeg conversion failed"):
                await _convert_to_pcm(b"bad-data")

    async def test_ffmpeg_no_output_raises(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("figaro_gateway.stt.asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(TranscriptionError, match="ffmpeg produced no output"):
                await _convert_to_pcm(b"silence")


class TestSendAudioChunks:
    """Tests for _send_audio_chunks — PCM chunking and stream close."""

    async def test_sends_chunks_and_close(self):
        ws = AsyncMock()
        # 6400 bytes = 2 chunks of 3200
        pcm_data = b"\x00" * 6400

        await _send_audio_chunks(ws, pcm_data)

        assert ws.send.call_count == 3  # 2 data chunks + CloseStream
        # First two calls are binary chunks
        assert ws.send.call_args_list[0][0][0] == pcm_data[:3200]
        assert ws.send.call_args_list[1][0][0] == pcm_data[3200:]
        # Last call is CloseStream
        close_msg = json.loads(ws.send.call_args_list[2][0][0])
        assert close_msg["type"] == "CloseStream"

    async def test_small_chunk_sends_one_plus_close(self):
        ws = AsyncMock()
        pcm_data = b"\x00" * 100

        await _send_audio_chunks(ws, pcm_data)

        assert ws.send.call_count == 2  # 1 data chunk + CloseStream


class TestReceiveTranscript:
    """Tests for _receive_transcript — WebSocket message collection."""

    async def test_collects_transcript(self):
        messages = [
            json.dumps({"type": "TranscriptText", "data": "hello"}),
            json.dumps({"type": "TranscriptEndpoint"}),
            json.dumps({"type": "TranscriptText", "data": "world"}),
            json.dumps({"type": "TranscriptEndpoint"}),
        ]
        ws = AsyncIteratorMock(messages)

        result = await _receive_transcript(ws)  # type: ignore[arg-type]  # duck-typed mock

        assert result == "hello world"

    async def test_transcript_error_raises(self):
        messages = [
            json.dumps({"type": "TranscriptError", "description": "bad audio"}),
        ]
        ws = AsyncIteratorMock(messages)

        with pytest.raises(TranscriptionError, match="STT error: bad audio"):
            await _receive_transcript(ws)  # type: ignore[arg-type]  # duck-typed mock

    async def test_promotes_trailing_interim_text(self):
        """Interim text without a final TranscriptEndpoint is still included."""
        messages = [
            json.dumps({"type": "TranscriptText", "data": "trailing"}),
        ]
        ws = AsyncIteratorMock(messages)

        result = await _receive_transcript(ws)  # type: ignore[arg-type]  # duck-typed mock

        assert result == "trailing"

    async def test_empty_transcript(self):
        messages = [
            json.dumps({"type": "TranscriptEndpoint"}),
        ]
        ws = AsyncIteratorMock(messages)

        result = await _receive_transcript(ws)  # type: ignore[arg-type]  # duck-typed mock

        assert result == ""


class TestTranscribeAudio:
    """Tests for transcribe_audio — end-to-end integration."""

    async def test_happy_path(self):
        messages = [
            json.dumps({"type": "TranscriptText", "data": "hello world"}),
            json.dumps({"type": "TranscriptEndpoint"}),
        ]

        mock_ws = AsyncIteratorMock(messages)

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("figaro_gateway.stt._convert_to_pcm", return_value=b"\x00" * 3200) as mock_convert,
            patch("figaro_gateway.stt.websockets.connect", return_value=mock_connect),
        ):
            result = await transcribe_audio(b"ogg-data", "token-123", "wss://claude.ai")

        assert result == "hello world"
        mock_convert.assert_called_once_with(b"ogg-data")

    async def test_websocket_error_wraps_in_transcription_error(self):
        with (
            patch("figaro_gateway.stt._convert_to_pcm", return_value=b"\x00" * 3200),
            patch("figaro_gateway.stt.websockets.connect", side_effect=OSError("connection refused")),
        ):
            with pytest.raises(TranscriptionError, match="STT WebSocket error"):
                await transcribe_audio(b"ogg-data", "token-123", "wss://claude.ai")

    async def test_ffmpeg_failure_propagates(self):
        with patch(
            "figaro_gateway.stt._convert_to_pcm",
            side_effect=TranscriptionError("ffmpeg conversion failed"),
        ):
            with pytest.raises(TranscriptionError, match="ffmpeg conversion failed"):
                await transcribe_audio(b"bad-data", "token-123", "wss://claude.ai")

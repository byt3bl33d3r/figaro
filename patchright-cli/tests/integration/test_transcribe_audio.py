"""Integration tests for the transcribe-audio command.

Requires:
- Real headless Chromium browser (via patchright)
- OPENAI_API_KEY environment variable (from .env or exported)

These tests verify the full pipeline: browser audio detection → download → Whisper transcription.
A local HTTP server serves audio files since Playwright's request API only supports http(s).
"""

from __future__ import annotations

import base64
import io
import math
import os
import struct
import urllib.parse
import wave
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

import pytest

from patchright_cli.captcha import find_audio_url, transcribe_audio
from patchright_cli.server import BrowserSession


def _generate_wav(duration: float = 1.0, frequency: float = 440.0) -> bytes:
    """Generate a short WAV file with a sine wave tone."""
    sample_rate = 16000
    n_samples = int(sample_rate * duration)
    samples = [
        int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
        for i in range(n_samples)
    ]
    buf = io.BytesIO()
    with wave.open(buf, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(struct.pack("<" + "h" * n_samples, *samples))
    return buf.getvalue()


WAV_BYTES = _generate_wav()


def _audio_data_url() -> str:
    """Return a data: URL containing a short WAV audio file."""
    b64 = base64.b64encode(WAV_BYTES).decode()
    return f"data:audio/wav;base64,{b64}"


class _AudioHandler(SimpleHTTPRequestHandler):
    """Serves WAV_BYTES at /audio.wav and an HTML page at /page.html."""

    def do_GET(self):
        if self.path == "/audio.wav":
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(WAV_BYTES)))
            self.end_headers()
            self.wfile.write(WAV_BYTES)
        elif self.path == "/page.html":
            html = b'<html><body><audio src="/audio.wav"></audio></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        else:
            self.send_error(404)

    def log_message(self, format, *args):  # noqa: A002
        pass  # Silence request logging during tests


@pytest.fixture(scope="module")
def audio_server():
    """Start a local HTTP server that serves test audio files."""
    server = HTTPServer(("127.0.0.1", 0), _AudioHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@pytest.mark.integration
class TestFindAudioUrlReal:
    """Test find_audio_url against a real browser DOM."""

    async def test_finds_audio_element(self, browser_session_real: BrowserSession):
        page = browser_session_real.active_page
        audio_url = _audio_data_url()
        html = f'<html><body><audio src="{audio_url}"></audio></body></html>'
        await page.goto("data:text/html," + urllib.parse.quote(html))

        result = await find_audio_url(page)
        assert result is not None
        assert result.startswith("data:audio/wav;base64,")

    async def test_no_audio_returns_none(self, browser_session_real: BrowserSession):
        page = browser_session_real.active_page
        await page.goto("data:text/html,<html><body><p>No audio here</p></body></html>")

        result = await find_audio_url(page)
        assert result is None

    async def test_finds_audio_in_iframe(self, browser_session_real: BrowserSession):
        page = browser_session_real.active_page
        audio_url = _audio_data_url()
        iframe_src = "data:text/html," + urllib.parse.quote(
            f'<html><body><audio src="{audio_url}"></audio></body></html>'
        )
        outer_html = f'<html><body><iframe src="{iframe_src}"></iframe></body></html>'
        await page.goto("data:text/html," + urllib.parse.quote(outer_html))
        await page.wait_for_timeout(1000)

        result = await find_audio_url(page)
        assert result is not None
        assert result.startswith("data:audio/wav;base64,")

    async def test_finds_audio_with_http_src(
        self, browser_session_real: BrowserSession, audio_server: str
    ):
        """Verify find_audio_url returns the http:// src from a real page."""
        page = browser_session_real.active_page
        await page.goto(f"{audio_server}/page.html")

        result = await find_audio_url(page)
        assert result == f"{audio_server}/audio.wav"


@pytest.mark.integration
@requires_openai_key
class TestTranscribeAudioReal:
    """Test Whisper transcription with real OpenAI API calls."""

    async def test_transcribe_sine_wave(self):
        """Whisper should return some text (even if empty) for a sine wave without error."""
        api_key = os.environ["OPENAI_API_KEY"]
        result = await transcribe_audio(WAV_BYTES, api_key)
        assert isinstance(result, str)

    async def test_cmd_transcribe_audio_with_url(
        self, browser_session_real: BrowserSession, audio_server: str
    ):
        """Full cmd_transcribe_audio pipeline with an explicit --url."""
        page = browser_session_real.active_page
        await page.goto("data:text/html,<html><body>empty</body></html>")

        result = await browser_session_real.cmd_transcribe_audio(
            url=f"{audio_server}/audio.wav"
        )
        assert result["ok"] is True
        assert "output" in result

    async def test_cmd_transcribe_audio_auto_detect(
        self, browser_session_real: BrowserSession, audio_server: str
    ):
        """Full cmd_transcribe_audio pipeline with auto-detected <audio> element."""
        page = browser_session_real.active_page
        await page.goto(f"{audio_server}/page.html")

        result = await browser_session_real.cmd_transcribe_audio()
        assert result["ok"] is True
        assert "output" in result

    async def test_cmd_transcribe_audio_saves_file(
        self, browser_session_real: BrowserSession, audio_server: str, tmp_path: Path
    ):
        """cmd_transcribe_audio with --filename saves the audio to disk."""
        page = browser_session_real.active_page
        await page.goto(f"{audio_server}/page.html")

        audio_path = str(tmp_path / "captured.wav")
        result = await browser_session_real.cmd_transcribe_audio(filename=audio_path)
        assert result["ok"] is True
        saved = Path(audio_path).read_bytes()
        assert len(saved) > 0


@pytest.mark.integration
class TestTranscribeAudioErrors:
    """Test error handling in real browser context."""

    async def test_no_api_key(
        self, browser_session_real: BrowserSession, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        page = browser_session_real.active_page
        await page.goto("data:text/html,<html><body>test</body></html>")

        result = await browser_session_real.cmd_transcribe_audio()
        assert result["ok"] is False
        assert "OPENAI_API_KEY" in result["error"]

    async def test_no_audio_element(
        self, browser_session_real: BrowserSession, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        page = browser_session_real.active_page
        await page.goto("data:text/html,<html><body>no audio</body></html>")

        result = await browser_session_real.cmd_transcribe_audio()
        assert result["ok"] is False
        assert "No audio element" in result["error"]

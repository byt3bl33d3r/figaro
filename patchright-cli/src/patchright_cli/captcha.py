"""Audio CAPTCHA transcription helpers for patchright-cli."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page

from openai import AsyncOpenAI


async def find_audio_url(page: Page) -> str | None:
    """Search all frames (main + iframes) for the first <audio> element src.

    Returns the ``src`` attribute value, or *None* if no audio element is found.
    """
    for frame in page.frames:
        src = await frame.evaluate("document.querySelector('audio')?.src || ''")
        if src:
            return src
    return None


async def transcribe_audio(audio_data: bytes, api_key: str) -> str:
    """Send *audio_data* to the OpenAI Whisper API and return the transcription text."""
    client = AsyncOpenAI(api_key=api_key)
    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=("audio.wav", BytesIO(audio_data)),
    )
    return transcript.text

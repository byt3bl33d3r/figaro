"""Speech-to-text transcription via Claude's STT WebSocket endpoint."""

import asyncio
import json
import logging
from pathlib import Path

import websockets

logger = logging.getLogger(__name__)

STT_ENDPOINT = "/api/ws/speech_to_text/voice_stream"
CHUNK_SIZE = 3200  # 100ms of 16kHz 16-bit mono PCM
TRANSCRIPTION_TIMEOUT = 30.0  # seconds


class TranscriptionError(Exception):
    """Raised when audio transcription fails."""


def load_oauth_token(credentials_path: Path) -> str | None:
    """Read OAuth token from Claude credentials file.

    Returns None if the file is missing or the token is absent.
    """
    if not credentials_path.exists():
        logger.warning(f"Credentials file not found: {credentials_path}")
        return None

    try:
        creds = json.loads(credentials_path.read_text())
        token = creds.get("claudeAiOauth", {}).get("accessToken")
        if not token:
            logger.warning("No claudeAiOauth.accessToken in credentials file")
            return None
        return token
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Failed to read credentials file: {exc}")
        return None


async def transcribe_audio(audio_data: bytes, oauth_token: str, base_url: str) -> str:
    """Transcribe audio data via Claude's STT WebSocket endpoint.

    Converts the input audio to PCM via ffmpeg, streams it to the STT endpoint,
    and returns the final transcript text.

    Raises TranscriptionError on failure.
    """
    pcm_data = await _convert_to_pcm(audio_data)

    url = (
        f"{base_url}{STT_ENDPOINT}"
        f"?encoding=linear16&sample_rate=16000&channels=1"
        f"&endpointing_ms=300&utterance_end_ms=1000&language=en"
    )
    headers = {
        "Authorization": f"Bearer {oauth_token}",
        "User-Agent": "claude-cli/2.1.72 (external, cli)",
        "x-app": "cli",
    }

    try:
        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.send(json.dumps({"type": "KeepAlive"}))
            await _send_audio_chunks(ws, pcm_data)
            return await _receive_transcript(ws)
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"STT WebSocket error: {exc}") from exc


async def _convert_to_pcm(audio_data: bytes) -> bytes:
    """Convert audio to raw PCM (16-bit LE, 16kHz, mono) via ffmpeg."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", "pipe:0",
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=audio_data)

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace").strip()
        raise TranscriptionError(f"ffmpeg conversion failed (exit {proc.returncode}): {error_msg}")

    if not stdout:
        raise TranscriptionError("ffmpeg produced no output")

    return stdout


async def _send_audio_chunks(ws: websockets.ClientConnection, pcm_data: bytes) -> None:
    """Send PCM data in chunks, then signal end of stream."""
    for offset in range(0, len(pcm_data), CHUNK_SIZE):
        chunk = pcm_data[offset : offset + CHUNK_SIZE]
        await ws.send(chunk)

    await ws.send(json.dumps({"type": "CloseStream"}))


async def _receive_transcript(ws: websockets.ClientConnection) -> str:
    """Collect transcript messages and return the final text."""
    final_text = ""
    interim_text = ""

    try:
        async with asyncio.timeout(TRANSCRIPTION_TIMEOUT):
            async for message in ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "TranscriptText":
                    interim_text = data.get("data", "")

                elif msg_type == "TranscriptEndpoint":
                    if interim_text:
                        if final_text:
                            final_text += " "
                        final_text += interim_text
                        interim_text = ""

                elif msg_type == "TranscriptError":
                    desc = data.get("description") or data.get("error_code") or "unknown"
                    raise TranscriptionError(f"STT error: {desc}")

    except TimeoutError as exc:
        raise TranscriptionError("STT transcription timed out") from exc

    # Promote any remaining interim text
    if interim_text:
        if final_text:
            final_text += " "
        final_text += interim_text

    return final_text

"""
stt.py — Speech-to-text via faster-whisper (CPU-only).

Transcribes audio/video files to Russian text using OpenAI Whisper
via the faster-whisper implementation. Runs entirely on CPU,
no GPU required.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def extract_audio(video_path: str) -> Optional[str]:
    """Extract audio track from video file using FFmpeg.

    Returns path to a temporary WAV file, or None on failure.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path,
             "-vn", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1",
             tmp_path],
            capture_output=True, timeout=300,
        )
        return tmp_path
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("FFmpeg failed: %s", exc)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return None


def transcribe(audio_path: str, model_size: str = "tiny") -> Optional[str]:
    """Transcribe audio file to Russian text using faster-whisper.

    Args:
        audio_path: Path to audio file (WAV, MP3, etc.)
        model_size: Model size: 'tiny'(~150MB), 'base'(~250MB), 'small'(~500MB)

    Returns:
        Transcribed text, or None on failure.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.error("faster-whisper not installed. Run: pip install faster-whisper")
        return None

    # Download/load model (cached in ~/.cache/whisper/ or %USERPROFILE%\.cache\whisper\)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, language="ru", beam_size=3)

    text_parts = []
    for seg in segments:
        text_parts.append(seg.text)

    return " ".join(text_parts)


def transcribe_video(video_path: str, model_size: str = "tiny") -> Optional[str]:
    """Full pipeline: extract audio → transcribe.

    Cleans up temporary audio file automatically.
    """
    audio = extract_audio(video_path)
    if audio is None:
        return None
    try:
        result = transcribe(audio, model_size=model_size)
        return result
    finally:
        if audio and os.path.exists(audio):
            os.unlink(audio)

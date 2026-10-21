"""Audio helpers: format handling and long-file chunking.

Format handling is deliberately thin — pydub/ffmpeg already decode essentially
any container (WAV, MP3, M4A, FLAC, OGG, ...), so we don't write per-format code.
We just load through ffmpeg and let it normalise.

For long files we split into fixed-length chunks. Each chunk is transcribed
independently (so they can run in parallel and fail/retry in isolation), then the
timestamps are shifted back onto the original timeline when results are merged.
"""
import os
import tempfile

from pydub import AudioSegment

from app.config import settings


def get_duration_seconds(path: str) -> float:
    audio = AudioSegment.from_file(path)
    return len(audio) / 1000.0


def needs_chunking(path: str) -> bool:
    return get_duration_seconds(path) > settings.chunk_threshold_seconds


def split_into_chunks(path: str) -> list[tuple[str, float]]:
    """Split audio into chunks on disk.

    Returns a list of (chunk_path, offset_seconds). The offset is how far into
    the original recording the chunk starts — used later to correct timestamps.
    """
    audio = AudioSegment.from_file(path)
    chunk_ms = settings.chunk_length_seconds * 1000
    tmpdir = tempfile.mkdtemp(prefix="chunks_")

    chunks: list[tuple[str, float]] = []
    for idx, start_ms in enumerate(range(0, len(audio), chunk_ms)):
        piece = audio[start_ms:start_ms + chunk_ms]
        chunk_path = os.path.join(tmpdir, f"chunk_{idx:04d}.wav")
        # Export to 16kHz mono WAV — exactly what Whisper wants, and avoids
        # re-decoding surprises inside the model.
        piece.set_frame_rate(16000).set_channels(1).export(chunk_path, format="wav")
        chunks.append((chunk_path, start_ms / 1000.0))

    return chunks


def merge_segments(results: list[tuple[list[dict], float]]) -> list[dict]:
    """Merge per-chunk segment lists, shifting timestamps by each chunk's offset.

    `results` is a list of (segments, offset_seconds) in chunk order.
    """
    merged: list[dict] = []
    next_id = 0
    for segments, offset in results:
        for seg in segments:
            merged.append({
                "id": next_id,
                "start": round(seg["start"] + offset, 2),
                "end": round(seg["end"] + offset, 2),
                "text": seg["text"].strip(),
            })
            next_id += 1
    return merged

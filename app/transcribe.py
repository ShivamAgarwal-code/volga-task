"""Transcription core, built on OpenAI's open-source Whisper.

Whisper is a good fit: open-source, runs offline (no per-request API cost, no
audio leaving the box), auto-detects language, and returns per-segment
timestamps for free. The model is loaded once per process and reused.
"""
from functools import lru_cache

import whisper

from app.audio_utils import merge_segments, needs_chunking, split_into_chunks
from app.config import settings


@lru_cache(maxsize=1)
def _get_model():
    # Loaded lazily and cached so each worker process holds exactly one model.
    return whisper.load_model(settings.whisper_model)


def _transcribe_file(path: str) -> dict:
    """Transcribe a single audio file (assumed short enough to handle directly)."""
    result = _get_model().transcribe(path, verbose=False)
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"]}
        for s in result["segments"]
    ]
    return {"language": result["language"], "segments": segments}


def transcribe(path: str) -> dict:
    """Transcribe an audio file of any length.

    Short files go straight through Whisper. Long files are split into chunks,
    transcribed chunk-by-chunk, and stitched back together with corrected
    timestamps. The chunk loop is sequential here for clarity; in production the
    chunks are independent and can be fanned out across workers.
    """
    if not needs_chunking(path):
        out = _transcribe_file(path)
        segments = [
            {"id": i, "start": round(s["start"], 2), "end": round(s["end"], 2),
             "text": s["text"].strip()}
            for i, s in enumerate(out["segments"])
        ]
        full_text = " ".join(s["text"] for s in segments).strip()
        return {"language": out["language"], "full_text": full_text, "segments": segments}

    # Long file: chunk -> transcribe each -> merge.
    chunks = split_into_chunks(path)
    language = None
    per_chunk: list[tuple[list[dict], float]] = []
    for chunk_path, offset in chunks:
        out = _transcribe_file(chunk_path)
        language = language or out["language"]
        per_chunk.append((out["segments"], offset))

    segments = merge_segments(per_chunk)
    full_text = " ".join(s["text"] for s in segments).strip()
    return {"language": language, "full_text": full_text, "segments": segments}

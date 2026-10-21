"""Standalone transcription — no API, queue, or storage required.

This is the simplest possible entry point: point it at an audio file and it
prints JSON with the full text plus per-segment timestamps. Handy for Part 1
and for sanity-checking Whisper locally before running the full stack.

Usage:
    python scripts/transcribe_cli.py path/to/audio.mp3
"""
import json
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, ".")

from app.transcribe import transcribe  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/transcribe_cli.py <audio-file>")
    result = transcribe(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

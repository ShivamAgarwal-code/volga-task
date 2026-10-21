"""Generate a short spoken-audio sample for testing, using offline TTS.

Usage:
    python scripts/generate_sample.py            # writes sample_data/sample.mp3

Needs pyttsx3 (offline, no network):  pip install pyttsx3
If you'd rather use your own clip, just drop any WAV/MP3 into sample_data/.
"""
import os
import sys

TEXT = (
    "Hello and welcome to the transcription pipeline demo. "
    "This is a short sample used to test the service end to end. "
    "It should come back as text with timestamps for each segment."
)


def main() -> None:
    out_path = os.path.join("sample_data", "sample.mp3")
    try:
        import pyttsx3
    except ImportError:
        sys.exit("pyttsx3 not installed. Run: pip install pyttsx3")

    engine = pyttsx3.init()
    engine.save_to_file(TEXT, out_path)
    engine.runAndWait()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

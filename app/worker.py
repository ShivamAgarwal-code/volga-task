"""Celery worker — where transcription actually runs.

The API never transcribes inline; it enqueues a job and returns immediately.
This is what lets the service absorb many concurrent uploads: the upload path
stays fast, and throughput is bounded by the number of workers, not by how many
requests arrive at once. Failed jobs retry with exponential backoff and, after
a few attempts, are marked FAILED with the error recorded for inspection.
"""
import os
import tempfile

from celery import Celery

from app.config import settings
from app.database import SessionLocal
from app.models import JobStatus, TranscriptionJob
from app.storage import download_to_file
from app.transcribe import transcribe

celery_app = Celery(
    "transcription",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_acks_late=True,            # redeliver if a worker dies mid-task
    worker_prefetch_multiplier=1,   # one heavy job at a time per worker slot
    task_track_started=True,
)

MAX_ATTEMPTS = 3


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,             # 1s, 2s, 4s ... between retries
    retry_kwargs={"max_retries": MAX_ATTEMPTS - 1},
)
def transcribe_job(self, job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        if job is None:
            return

        job.status = JobStatus.PROCESSING
        job.attempts += 1
        db.commit()

        # Pull the audio from object storage to a temp file for ffmpeg/whisper.
        suffix = os.path.splitext(job.original_filename or "")[1] or ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        try:
            download_to_file(job.audio_key, tmp_path)
            result = transcribe(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        job.language = result["language"]
        job.full_text = result["full_text"]
        job.segments = result["segments"]
        job.status = JobStatus.DONE
        job.error = None
        db.commit()

    except Exception as exc:  # noqa: BLE001 — record, then re-raise for retry
        job = db.get(TranscriptionJob, job_id)
        if job is not None:
            job.error = str(exc)
            # On the final attempt, park it as FAILED (dead-letter equivalent).
            if self.request.retries >= MAX_ATTEMPTS - 1:
                job.status = JobStatus.FAILED
            db.commit()
        raise
    finally:
        db.close()

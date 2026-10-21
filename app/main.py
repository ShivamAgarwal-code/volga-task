"""FastAPI entry point.

Three endpoints, async by design:
  POST /transcriptions           -> accept an upload, enqueue, return a job_id (202)
  GET  /transcriptions/{job_id}  -> poll status / fetch the finished transcript
  GET  /transcriptions           -> list recent jobs

The upload handler does only cheap work (validate, store, enqueue) so it stays
responsive under concurrent load. The heavy lifting happens in the Celery worker.
"""
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, init_db
from app.models import JobStatus, TranscriptionJob
from app.schemas import JobCreated, JobStatusResponse
from app.storage import ensure_bucket, put_audio
from app.worker import transcribe_job

app = FastAPI(
    title="Transcription Pipeline",
    description="Audio -> text with per-segment timestamps. Async, queue-backed.",
    version="1.0.0",
)

ALLOWED_CONTENT_PREFIXES = ("audio/", "video/")   # video containers carry audio
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4"}


@app.on_event("startup")
def _startup() -> None:
    init_db()
    ensure_bucket()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _looks_like_audio(file: UploadFile) -> bool:
    if file.content_type and file.content_type.startswith(ALLOWED_CONTENT_PREFIXES):
        return True
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    return ext in ALLOWED_EXTENSIONS


@app.post(
    "/transcriptions",
    response_model=JobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_transcription(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> JobCreated:
    if not _looks_like_audio(file):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File does not appear to be a supported audio/video format.",
        )

    # Read with a hard size cap so a huge upload can't exhaust memory/disk.
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_mb} MB limit.",
        )

    # Store audio in object storage under a unique key; DB keeps only the pointer.
    audio_key = f"{uuid.uuid4()}/{file.filename}"
    put_audio(audio_key, data, file.content_type)

    job = TranscriptionJob(
        audio_key=audio_key,
        original_filename=file.filename,
        content_type=file.content_type,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Hand off to the worker pool and return right away.
    transcribe_job.delay(job.id)

    return JobCreated(job_id=job.id, status=job.status.value)


@app.get("/transcriptions/{job_id}", response_model=JobStatusResponse)
def get_transcription(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatusResponse(**job.to_dict())


@app.get("/transcriptions", response_model=list[JobStatusResponse])
def list_transcriptions(limit: int = 20, db: Session = Depends(get_db)):
    jobs = (
        db.query(TranscriptionJob)
        .order_by(TranscriptionJob.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return [JobStatusResponse(**j.to_dict()) for j in jobs]

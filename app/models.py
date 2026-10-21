"""Database models.

A single `jobs` table tracks the full lifecycle of one upload. The audio itself
lives in object storage; here we only keep a pointer (`audio_key`) plus metadata
and the resulting transcript. Transcripts are stored as JSON because the segment
structure is naturally nested and we rarely query inside it.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"          # accepted, waiting for a worker
    PROCESSING = "processing"    # a worker picked it up
    DONE = "done"
    FAILED = "failed"            # exhausted retries


def _uuid() -> str:
    return str(uuid.uuid4())


class TranscriptionJob(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)

    # Where the original audio lives in object storage.
    audio_key = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)

    # Results (populated when status == DONE).
    language = Column(String, nullable=True)
    full_text = Column(Text, nullable=True)
    segments = Column(JSONB, nullable=True)      # list of {id, start, end, text}

    # Diagnostics.
    error = Column(Text, nullable=True)
    attempts = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "original_filename": self.original_filename,
            "language": self.language,
            "full_text": self.full_text,
            "segments": self.segments,
            "error": self.error,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

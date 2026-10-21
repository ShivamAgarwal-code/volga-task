"""Pydantic response models — the public shape of the API."""
from pydantic import BaseModel


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str


class JobCreated(BaseModel):
    job_id: str
    status: str
    message: str = "Upload accepted. Poll GET /transcriptions/{job_id} for the result."


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    original_filename: str | None = None
    language: str | None = None
    full_text: str | None = None
    segments: list[Segment] | None = None
    error: str | None = None
    attempts: int = 0
    created_at: str | None = None
    updated_at: str | None = None

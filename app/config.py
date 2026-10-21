"""Central configuration, loaded from environment variables.

Keeping all config in one typed object means the rest of the code never reads
os.environ directly, and swapping a dependency (e.g. local disk instead of S3)
is a one-line change here rather than a hunt through the codebase.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Persistence
    database_url: str = "postgresql://postgres:postgres@localhost:5432/transcriptions"

    # Queue
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (S3-compatible)
    s3_endpoint_url: str | None = None          # None => real AWS S3
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "audio-uploads"
    s3_region: str = "us-east-1"

    # Transcription
    whisper_model: str = "base"
    chunk_threshold_seconds: int = 600          # split files longer than this
    chunk_length_seconds: int = 300             # size of each chunk

    # Uploads
    max_upload_mb: int = 100

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()

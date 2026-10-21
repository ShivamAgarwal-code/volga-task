# Transcription Pipeline

A service that accepts an audio file, transcribes it to text with **per-segment
timestamps**, and processes the result for downstream use. Built around
open-source [Whisper](https://github.com/openai/whisper), FastAPI, Celery,
Postgres, Redis, and S3-compatible object storage.

The brief asks to see engineering judgement rather than a from-scratch model, so
this README focuses on **why** the pieces are shaped the way they are.

---

## What it does

```
             ┌──────────┐   enqueue    ┌──────────┐   result    ┌──────────┐
 upload ───▶ │ FastAPI  │ ───────────▶ │  Redis   │ ──────────▶ │  Celery  │
 (audio)     │   API    │   job_id     │  queue   │             │  worker  │
             └────┬─────┘              └──────────┘             └────┬─────┘
                  │ store audio              poll                    │ Whisper
                  ▼                           ▲                      ▼ (+ chunking)
             ┌──────────┐                     │               transcript JSON
             │  MinIO/  │                     │                     │
             │   S3     │                ┌────┴─────┐               │
             └──────────┘                │ Postgres │ ◀─────────────┘
                                         │ (status, │
                                         │ segments)│
                                         └──────────┘
```

1. **POST** an audio file → the API validates it, stores the blob in object
   storage, writes a `pending` job row, enqueues it, and returns a `job_id`
   immediately (HTTP `202`).
2. A **worker** picks the job up, pulls the audio, transcribes it (chunking long
   files), and writes the transcript + segments back to Postgres.
3. **GET** `/transcriptions/{job_id}` → status, and once done, the transcript
   with timestamps.

---

## Quick start

```bash
cp .env.example .env
docker compose up --build        # API on http://localhost:8000
```

Then:

```bash
# submit
curl -F "file=@sample_data/sample.mp3" http://localhost:8000/transcriptions
# -> {"job_id": "…", "status": "pending", ...}

# poll
curl http://localhost:8000/transcriptions/<job_id>
```

Interactive docs (Swagger) are auto-generated at `http://localhost:8000/docs`.

### Just want the transcription, no infra?

```bash
pip install -r requirements.txt   # needs ffmpeg installed
python scripts/transcribe_cli.py sample_data/sample.mp3
```

Example output:

```json
{
  "language": "en",
  "full_text": "Hello and welcome to the transcription pipeline demo...",
  "segments": [
    { "id": 0, "start": 0.0, "end": 3.1, "text": "Hello and welcome to the transcription pipeline demo." },
    { "id": 1, "start": 3.1, "end": 6.4, "text": "This is a short sample used to test the service end to end." }
  ]
}
```

---

## Design decisions

### Why Whisper
Open-source, runs offline (no per-request cost, no audio leaving the host),
robust on real-world audio (accents, noise), auto-detects language, and gives
**per-segment timestamps out of the box**. The model is wrapped behind a single
`transcribe(path)` function, so swapping in a hosted API (Deepgram, AssemblyAI)
later is a one-file change. Model size is configurable (`WHISPER_MODEL`): `base`
for speed, `small`/`medium` for accuracy.

### Async by default (handling concurrent uploads)
Transcription is slow and resource-heavy, so it **never runs inline with the
request**. The API only validates, stores, and enqueues — all cheap — then
returns a `job_id`. Actual work happens in a Celery worker pool reading from
Redis. This means:
- The upload endpoint stays responsive no matter how many requests land at once.
- Throughput scales with worker count (`docker compose up --scale worker=3`),
  not with request volume — a spike just queues instead of crashing anything.
- `worker_prefetch_multiplier=1` keeps one heavy job per slot so a machine
  doesn't try to run many Whisper models at once.

### Storage: blobs vs metadata
Two stores because they have different shapes:
- **Audio → object storage** (S3 / MinIO). Large binaries don't belong in a
  database; the DB keeps only a pointer (`audio_key`).
- **Metadata + transcripts → Postgres.** Status, language, attempts, errors, and
  the segment list (as `JSONB`, since the structure is naturally nested).

Audio is large and usually not needed forever, so a real deployment would attach
a lifecycle/retention policy (expire or move to cold storage) while keeping the
small transcripts longer. The `storage.py` abstraction is the only code that
knows about buckets, so the provider can change without touching anything else.

### Different audio formats
Handled by **not** special-casing them. Whisper/pydub pipe everything through
**ffmpeg**, which decodes virtually any container (WAV, MP3, M4A, FLAC, OGG, and
even the audio track of a video file) and resamples to the 16 kHz mono Whisper
expects. The only format-specific code is a lightweight **validation** step at
upload time that rejects obvious non-audio early with a clear `415`, so callers
get a good error instead of a failure deep in a worker.

### Long audio files (chunking)
Whisper already windows audio internally, but a multi-hour file loaded at once is
slow, memory-hungry, and all-or-nothing on failure. So files longer than
`CHUNK_THRESHOLD_SECONDS` are **split into chunks** (`audio_utils.split_into_chunks`),
each transcribed independently, then **merged with timestamps shifted back onto
the original timeline** (`merge_segments`). Benefits:
- Chunks are independent → they can be fanned out across workers in parallel.
- A failure in one chunk only retries that chunk, not the whole recording.
- Bounded, predictable memory per chunk.

### Retry & recovery
Resilience falls out of the queue + status model:
- `task_acks_late=True` → if a worker dies mid-job, the task is redelivered
  rather than lost.
- Transient failures **auto-retry with exponential backoff** (`retry_backoff`).
- After `MAX_ATTEMPTS`, the job is parked as `failed` with the error string
  recorded (a dead-letter equivalent) for a human to inspect — it doesn't retry
  forever.
- Every step writes status to Postgres, so work is **idempotent**: rerunning a
  job can't duplicate or corrupt results.

### Exposing it as an API
A small, documented REST surface built on FastAPI (async-friendly, free
OpenAPI/Swagger docs):

| Method | Path                        | Purpose                                   |
|--------|-----------------------------|-------------------------------------------|
| POST   | `/transcriptions`           | Upload audio → returns `job_id` (`202`)   |
| GET    | `/transcriptions/{job_id}`  | Status + transcript with segments         |
| GET    | `/transcriptions`           | List recent jobs                          |
| GET    | `/health`                   | Liveness check                            |

The async job pattern is the key choice: the client never blocks on a long
request, and the same contract works for a 20-second clip or a 3-hour recording.

---

## Project layout

```
app/
  main.py          FastAPI endpoints (upload / status / list)
  worker.py        Celery task: retries, status transitions
  transcribe.py    Whisper wrapper + long-file orchestration
  audio_utils.py   format handling, chunking, timestamp merge
  storage.py       S3/MinIO abstraction for audio blobs
  models.py        Job table (status, segments as JSONB)
  schemas.py       API request/response shapes
  config.py        typed settings from env
  database.py      SQLAlchemy engine/session
scripts/
  transcribe_cli.py   standalone transcription, no infra
  generate_sample.py  make a test clip offline
tests/
  test_api.py         API contract smoke tests
docker-compose.yml    full stack: api, worker, db, redis, minio
```

## Running tests

```bash
pip install -r requirements.txt
pytest
```

---

## Production hardening (what I'd add next)

Deliberately out of scope for a take-home, but the honest next steps:

- **Auth** (API keys / JWT) and per-client rate limiting on the upload endpoint.
- **Alembic migrations** instead of `create_all`.
- **Webhooks** so clients are notified on completion instead of polling.
- **Parallel chunk fan-out** across workers for very long files (the chunk
  interface already supports it).
- **Observability**: structured logs, metrics (queue depth, job latency),
  tracing, and a dead-letter dashboard.
- **Object-storage lifecycle** rules for audio retention.
```

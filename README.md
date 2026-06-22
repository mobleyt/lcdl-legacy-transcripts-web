# Transcripts Web Admin

A small web UI that wraps the existing `aviary_sync.py` and `convert.py` scripts
so non-technical staff can download and convert legacy transcripts from a
browser instead of the command line.

## What it does

1. **Sign in** with a shared admin password.
2. **Pick an Aviary collection** (fetched live from the API).
3. **Upload a CSV** of legacy materials — same columns the script expects:
   `rspace-id`, `collectiontitle`, `filepath`.
4. **Choose output**: converted text (`.txt`), original PDFs (`.pdf`), or both;
   optionally strip MM:SS timestamp columns.
5. The server runs the pipeline in the background — *match → download PDFs →
   convert → zip* — streaming progress to the page, then offers a **zip
   download** of the results.

Under the hood it imports the two scripts as libraries and reuses their logic;
the web layer only orchestrates and reports progress. See `webapp/` for the
FastAPI app.

## Configuration

All secrets come from the environment (never the browser). Copy `.env.example`
to `.env` and fill in:

| Variable          | Purpose                                              |
| ----------------- | ---------------------------------------------------- |
| `AVIARY_API_KEY`  | Aviary API key used server-side for every request.   |
| `APP_PASSWORD`    | Shared password that gates the whole UI.             |
| `SECRET_KEY`      | Signs the session cookie (`python -c "import secrets;print(secrets.token_hex(32))"`). |
| `DATA_DIR`        | Where job working dirs / output zips go (optional).  |

## Run with Docker (recommended)

```bash
cp .env.example .env        # then edit .env
docker compose up --build   # serves on http://<host>:8000
```

The `transcript-data` volume holds in-progress jobs and result zips.

## Run locally for development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export AVIARY_API_KEY=...   # or use a .env loader
export APP_PASSWORD=changeme SECRET_KEY=dev
uvicorn webapp.main:app --reload --port 8000
```

> Note: use Python 3.12 (the Docker image's version). Python 3.14 is still
> pre-release and not all dependencies support it.

## Notes & limitations

- **Jobs live in memory.** Progress and result zips are tracked per process; a
  restart loses in-flight jobs. That's fine for a single-user internal tool. If
  you later need persistence or multiple workers, swap the in-memory registry in
  `webapp/jobs.py` for a queue/worker (e.g. RQ + Redis).
- **One shared password, no per-user accounts.** Put it behind your network /
  VPN as well; the password is a gate, not a full auth system.
- Long jobs (hundreds of resources) are expected — the API calls are
  rate-limited (0.5s each) in `aviary_sync.py`, so a large collection takes a
  while. The live progress log shows what's happening.

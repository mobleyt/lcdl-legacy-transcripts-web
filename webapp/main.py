"""FastAPI application: login, collection picker, job submission, live progress.

Run with:  uvicorn webapp.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import auth, config, pipeline
from .jobs import JobRegistry, JobStatus, stream_end

config.ensure_dirs()

app = FastAPI(title="LCDL Legacy Transcripts")
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)

_pkg_dir = config.BASE_DIR / "webapp"
app.mount("/static", StaticFiles(directory=str(_pkg_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_pkg_dir / "templates"))

registry = JobRegistry(config.JOBS_DIR)
_quiet_logger = logging.getLogger("aviary_sync.collections")
_quiet_logger.addHandler(logging.NullHandler())


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if auth.is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if auth.check_password(password):
        request.session["authed"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Incorrect password."}, status_code=401
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --------------------------------------------------------------------------- #
# Main page + collection list
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth.require_login)])
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/collections", dependencies=[Depends(auth.require_login)])
async def list_collections():
    """Live fetch of Aviary collections for the picker dropdown."""
    if not config.AVIARY_API_KEY:
        return {"error": "Server API key not configured."}
    client = pipeline.sync.AviaryClient(config.AVIARY_API_KEY, _quiet_logger)
    if not client.authenticate():
        return {"error": "Aviary authentication failed."}
    collections = client.get_collections()
    return {
        "collections": [
            {
                "id": c.get("id"),
                "title": c.get("title", f"Collection {c.get('id')}"),
                "resources_count": c.get("resources_count"),
            }
            for c in collections
        ]
    }


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@app.post("/jobs", dependencies=[Depends(auth.require_login)])
async def create_job(
    csv_file: UploadFile,
    collection_id: int = Form(...),
    collection_title: str = Form(...),
    formats: list[str] = Form(...),
    strip_timestamps: bool = Form(False),
):
    raw = await csv_file.read()
    if len(raw) > config.MAX_CSV_BYTES:
        return RedirectResponse("/?error=csv_too_large", status_code=303)

    chosen = {f for f in formats if f in ("txt", "pdf")} or {"txt"}
    job = registry.create(
        {
            "collection_id": collection_id,
            "collection_title": collection_title,
            "formats": chosen,
            "strip_timestamps": strip_timestamps,
        }
    )
    (job.work_dir / "input.csv").write_bytes(raw)
    registry.start(job, pipeline.run)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse, dependencies=[Depends(auth.require_login)])
async def job_page(request: Request, job_id: str):
    job = registry.get(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "job.html", {"job_id": job_id, "params": job.params}
    )


@app.get("/jobs/{job_id}/events", dependencies=[Depends(auth.require_login)])
async def job_events(job_id: str):
    job = registry.get(job_id)
    if not job:
        return StreamingResponse(iter(()), media_type="text/event-stream")

    end = stream_end()

    def event_stream():
        sub = job.subscribe()
        try:
            while True:
                item = sub.get()
                if item is end:
                    yield f"data: {json.dumps({'type': 'end'})}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            job.unsubscribe(sub)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/jobs/{job_id}/download", dependencies=[Depends(auth.require_login)])
async def job_download(job_id: str):
    job = registry.get(job_id)
    if not job or job.status != JobStatus.DONE or not job.result_zip:
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    from fastapi.responses import FileResponse

    return FileResponse(
        path=str(job.result_zip),
        media_type="application/zip",
        filename=job.result_zip.name,
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True, "api_key_configured": bool(config.AVIARY_API_KEY)}

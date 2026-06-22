"""Orchestrates the full pipeline for one job, reusing the existing scripts.

Flow:  authenticate -> phase1 (build resources for the chosen collection)
       -> phase2 (match against uploaded CSV) -> phase3 (download PDFs only)
       -> convert each PDF to text -> zip the requested formats.

The existing CLI scripts (``aviary_sync`` and ``convert``) are imported and
used as libraries; their logging is routed into the job's live event stream so
progress shows up in the browser.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import aviary_sync as sync
from convert import convert_pdf

from . import config
from .jobs import Job


class _JobLogHandler(logging.Handler):
    """Forwards log records from the sync script into a job's event stream."""

    def __init__(self, job: Job):
        super().__init__()
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.job.log(record.getMessage())
        except Exception:  # noqa: BLE001 - logging must never crash the job
            pass


def _make_logger(job: Job) -> logging.Logger:
    """A logger that feeds the job stream instead of the console."""
    logger = logging.getLogger(f"aviary_sync.{job.id}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(_JobLogHandler(job))
    return logger


def run(job: Job) -> None:
    params = job.params
    logger = _make_logger(job)

    csv_path: Path = job.work_dir / "input.csv"
    downloads_dir: Path = job.work_dir / "downloads"
    formats = params["formats"]  # subset of {"txt", "pdf"}
    strip_timestamps: bool = params["strip_timestamps"]

    if not config.AVIARY_API_KEY:
        raise RuntimeError("AVIARY_API_KEY is not configured on the server.")

    result = sync.SyncResult()
    client = sync.AviaryClient(config.AVIARY_API_KEY, logger)

    job.emit("status", "Authenticating with Aviary…", phase="auth")
    if not client.authenticate():
        raise RuntimeError("Aviary authentication failed (check the server API key).")

    collection = {"id": int(params["collection_id"]), "title": params["collection_title"]}

    job.emit("status", "Fetching resources…", phase="phase1")
    resources = sync.phase1_build_resource_list(
        client=client, logger=logger, result=result, collection_filter=collection
    )
    if not resources:
        raise RuntimeError("No resources found in the selected collection.")

    job.emit("status", "Matching resources against your CSV…", phase="phase2")
    pdf_data = sync.load_legacy_pdf_csv(csv_path, logger)
    if not pdf_data:
        raise RuntimeError("No usable rows found in the uploaded CSV.")
    sync.phase2_match_pdfs(resources, pdf_data, logger, result)
    if result.resources_matched_pdf == 0:
        raise RuntimeError(
            "No resources matched any CSV row by ResourceSpace ID — nothing to download."
        )

    job.emit("status", "Downloading PDFs…", phase="phase3")
    sync.phase3_download_files(
        resources=resources, output_dir=downloads_dir, logger=logger,
        result=result, dry_run=False, pdf_only=True,
    )

    pdfs = sorted(downloads_dir.rglob("*.pdf"))
    txt_paths: list[Path] = []
    if "txt" in formats:
        job.emit("status", f"Converting {len(pdfs)} PDF(s) to text…", phase="convert")
        for i, pdf in enumerate(pdfs, 1):
            txt = pdf.with_suffix(".txt")
            job.log(f"  [{i}/{len(pdfs)}] Converting {pdf.name}")
            try:
                convert_pdf(pdf, txt, strip_timestamps=strip_timestamps)
                txt_paths.append(txt)
            except Exception as exc:  # noqa: BLE001
                job.log(f"  ERROR converting {pdf.name}: {exc}")
                result.add_error("Convert", f"Failed to convert {pdf.name}", {"error": str(exc)})

    job.emit("status", "Packaging results…", phase="package")
    zip_path = _build_zip(job, downloads_dir, formats, pdfs, txt_paths)
    job.result_zip = zip_path

    summary = (
        f"Matched {result.resources_matched_pdf} resource(s); "
        f"downloaded {len(pdfs)} PDF(s)"
        + (f", converted {len(txt_paths)} to text" if "txt" in formats else "")
        + (f"; {len(result.errors)} error(s)" if result.errors else "")
        + "."
    )
    job.emit("status", summary, phase="package")


def _build_zip(
    job: Job, downloads_dir: Path, formats: set[str],
    pdfs: list[Path], txt_paths: list[Path],
) -> Path:
    """Zip the requested file types, preserving the Collection/Title layout."""
    zip_path = job.work_dir / f"transcripts-{job.id}.zip"
    members: list[Path] = []
    if "pdf" in formats:
        members += pdfs
    if "txt" in formats:
        members += txt_paths

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in members:
            zf.write(path, arcname=str(path.relative_to(downloads_dir)))

    job.log(f"Wrote {len(members)} file(s) to archive.")
    return zip_path

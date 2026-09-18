"""Report generation endpoints (Module 11)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from backend.app.api.deps import PipelineDep, SessionDep, SettingsDep
from backend.app.services.reports import build_report, export_csv, export_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", summary="Generate a report")
async def get_report(
    session: SessionDep,
    pipeline: PipelineDep,
    settings: SettingsDep,
    period: Literal["daily", "weekly", "monthly"] = Query(default="daily"),
    fmt: Literal["json", "csv", "pdf"] = Query(default="json", alias="format"),
):
    """Build a daily, weekly or monthly report in JSON, CSV or PDF.

    The reporting period is anchored to the latest *simulated* timestamp, not
    to real wall-clock time -- otherwise a run of the evening scenario would
    produce an empty "today".
    """
    # Make sure anything still sitting in the write buffer is in the database
    # before we aggregate over it, or the report silently omits the last few
    # seconds of the run.
    await pipeline.flush()
    report = build_report(session, pipeline.run_id, period, pipeline.tariff)

    if fmt == "json":
        return report

    if fmt == "csv":
        path = export_csv(report, settings.reports_dir)
        media_type = "text/csv"
    else:
        path = export_pdf(report, settings.reports_dir)
        media_type = "application/pdf"

    return FileResponse(path=path, media_type=media_type, filename=path.name)


@router.get("/files", summary="Previously exported report files")
def list_report_files(settings: SettingsDep) -> dict:
    directory = settings.reports_dir
    files = []
    for path in sorted(
        directory.glob("nilm-*-report-*"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        files.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "format": path.suffix.lstrip("."),
                "modified": path.stat().st_mtime,
            }
        )
    return {"files": files[:50], "directory": str(directory)}

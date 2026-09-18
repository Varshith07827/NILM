"""Report generation and export (Module 11).

Reports are built from the hourly ``energy_buckets`` table rather than from the
per-second ``readings`` table.  A month of simulated time is 2.6 million
readings but only 720 buckets, so a monthly report is a single indexed
aggregate rather than a full scan -- the reason the buckets exist at all.

Three output formats:

``json``  the structured report, consumed by the dashboard
``csv``   per-appliance rows plus an hourly series, for spreadsheets
``pdf``   a typeset one-page summary suitable for printing into a project file
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Reading
from backend.app.db.repositories.energy import (
    TOTAL_KEY,
    UNATTRIBUTED_KEY,
    EnergyRepository,
)
from backend.app.services.cost import Tariff
from simulator.appliances import APPLIANCES_BY_ID

ReportPeriod = Literal["daily", "weekly", "monthly"]

PERIOD_DURATION: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

DISPLAY_NAMES: dict[str, str] = {
    TOTAL_KEY: "Whole house",
    UNATTRIBUTED_KEY: "Unattributed",
}

DISPLAY_COLOURS: dict[str, str] = {
    TOTAL_KEY: "#94a3b8",
    UNATTRIBUTED_KEY: "#64748b",
}


@dataclass
class ReportWindow:
    start: datetime | None
    end: datetime | None


def _resolve_window(session: Session, run_id: str, period: ReportPeriod) -> ReportWindow:
    """Anchor the report to the latest *simulated* timestamp in the run."""
    latest = session.execute(
        select(func.max(Reading.sim_time)).where(Reading.run_id == run_id)
    ).scalar()
    if latest is None:
        return ReportWindow(start=None, end=None)

    end = latest + timedelta(seconds=1)
    start = end - PERIOD_DURATION[period]
    return ReportWindow(start=start, end=end)


def build_report(
    session: Session,
    run_id: str,
    period: ReportPeriod,
    tariff: Tariff,
) -> dict:
    """Assemble a structured report for the given period."""
    window = _resolve_window(session, run_id, period)
    energy_repo = EnergyRepository(session)

    totals = energy_repo.totals_by_appliance(run_id, window.start, window.end)
    by_id = {row["appliance_id"]: row for row in totals}

    house = by_id.get(TOTAL_KEY, {"energy_wh": 0.0, "cost_inr": 0.0, "peak_power_w": 0.0})
    total_wh = float(house["energy_wh"])
    total_cost = float(house["cost_inr"])

    appliances = []
    for row in totals:
        appliance_id = row["appliance_id"]
        if appliance_id == TOTAL_KEY:
            continue
        spec = APPLIANCES_BY_ID.get(appliance_id)
        appliances.append(
            {
                "appliance_id": appliance_id,
                "name": spec.name if spec else DISPLAY_NAMES.get(appliance_id, appliance_id),
                "colour": spec.colour if spec else DISPLAY_COLOURS.get(appliance_id, "#64748b"),
                "energy_wh": round(row["energy_wh"], 2),
                "energy_kwh": round(row["energy_wh"] / 1000.0, 4),
                "cost_inr": round(row["cost_inr"], 2),
                "runtime_s": round(row["runtime_s"], 0),
                "peak_power_w": round(row["peak_power_w"], 1),
                "share": round(row["energy_wh"] / total_wh, 4) if total_wh > 0 else 0.0,
            }
        )
    appliances.sort(key=lambda row: row["energy_wh"], reverse=True)

    hourly = energy_repo.hourly_series(run_id, window.start, window.end)
    daily = energy_repo.daily_series(run_id)

    # Average power over the period actually covered by data.
    if window.start and window.end and hourly:
        covered_hours = max(len(hourly), 1)
        average_power = total_wh / covered_hours
    else:
        average_power = 0.0

    return {
        "period": period,
        "generated_at": datetime.now(),
        "start": window.start,
        "end": window.end,
        "run_id": run_id,
        "total_energy_kwh": round(total_wh / 1000.0, 4),
        "total_cost_inr": round(total_cost, 2),
        "peak_power_w": round(float(house.get("peak_power_w", 0.0)), 1),
        "average_power_w": round(average_power, 1),
        "appliances": appliances,
        "hourly": [
            {
                "bucket_start": row["bucket_start"].isoformat(),
                "energy_wh": round(row["energy_wh"], 3),
                "cost_inr": round(row["cost_inr"], 3),
            }
            for row in hourly
        ],
        "daily": [
            {
                "day": row["day"],
                "energy_wh": round(row["energy_wh"], 2),
                "energy_kwh": round(row["energy_wh"] / 1000.0, 3),
                "cost_inr": round(row["cost_inr"], 2),
            }
            for row in daily
        ],
        "tariff": tariff.to_dict(),
        "slab_breakdown": tariff.slab_breakdown(total_wh / 1000.0),
    }


# --------------------------------------------------------------------------- #
# Exporters
# --------------------------------------------------------------------------- #


def _timestamped(directory: Path, period: str, extension: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return directory / f"nilm-{period}-report-{stamp}.{extension}"


def export_csv(report: dict, directory: Path) -> Path:
    """Write the report as CSV: a summary block, appliances, then hourly rows."""
    path = _timestamped(directory, report["period"], "csv")
    symbol = report["tariff"]["currency_symbol"]

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)

        writer.writerow(["Edge AI NILM Smart Meter", f"{report['period'].title()} Report"])
        writer.writerow(["Generated", report["generated_at"].isoformat(timespec="seconds")])
        writer.writerow(["Period start", report["start"].isoformat() if report["start"] else ""])
        writer.writerow(["Period end", report["end"].isoformat() if report["end"] else ""])
        writer.writerow(["Tariff", report["tariff"]["name"]])
        writer.writerow([])

        writer.writerow(["SUMMARY"])
        writer.writerow(["Total energy (kWh)", report["total_energy_kwh"]])
        writer.writerow([f"Total cost ({symbol})", report["total_cost_inr"]])
        writer.writerow(["Peak power (W)", report["peak_power_w"]])
        writer.writerow(["Average power (W)", report["average_power_w"]])
        writer.writerow([])

        writer.writerow(["APPLIANCE BREAKDOWN"])
        writer.writerow(
            [
                "Appliance",
                "Energy (kWh)",
                f"Cost ({symbol})",
                "Runtime (h)",
                "Peak power (W)",
                "Share (%)",
            ]
        )
        for row in report["appliances"]:
            writer.writerow(
                [
                    row["name"],
                    row["energy_kwh"],
                    row["cost_inr"],
                    round(row["runtime_s"] / 3600.0, 2),
                    row["peak_power_w"],
                    round(row["share"] * 100.0, 2),
                ]
            )
        writer.writerow([])

        writer.writerow(["HOURLY CONSUMPTION"])
        writer.writerow(["Hour", "Energy (Wh)", f"Cost ({symbol})"])
        for row in report["hourly"]:
            writer.writerow([row["bucket_start"], row["energy_wh"], row["cost_inr"]])

    return path


def export_pdf(report: dict, directory: Path) -> Path:
    """Typeset the report as a one-page PDF using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    path = _timestamped(directory, report["period"], "pdf")
    symbol = report["tariff"]["currency_symbol"]

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "NilmTitle",
        parent=styles["Title"],
        fontSize=18,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "NilmSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#64748b"),
    )
    section_style = ParagraphStyle(
        "NilmSection",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#0369a1"),
        spaceBefore=10,
        spaceAfter=4,
    )

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"NILM {report['period']} report",
        author="Edge AI NILM Smart Meter",
    )

    story: list = [
        Paragraph("Edge AI NILM Smart Meter", title_style),
        Paragraph(
            f"{report['period'].title()} energy report &nbsp;&bull;&nbsp; generated "
            f"{report['generated_at']:%d %b %Y %H:%M}",
            subtitle_style,
        ),
        Spacer(1, 4),
        HRFlowable(width="100%", color=colors.HexColor("#cbd5e1"), thickness=0.8),
    ]

    period_start = report["start"].strftime("%d %b %Y %H:%M") if report["start"] else "-"
    period_end = report["end"].strftime("%d %b %Y %H:%M") if report["end"] else "-"

    story.append(Paragraph("Summary", section_style))
    summary = Table(
        [
            ["Period", f"{period_start}  to  {period_end}"],
            ["Total energy", f"{report['total_energy_kwh']:.3f} kWh"],
            ["Total cost", f"{symbol}{report['total_cost_inr']:,.2f}"],
            ["Peak demand", f"{report['peak_power_w']:,.0f} W"],
            ["Average load", f"{report['average_power_w']:,.0f} W"],
            ["Tariff", report["tariff"]["name"]],
        ],
        colWidths=[45 * mm, None],
    )
    summary.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    story.append(summary)

    story.append(Paragraph("Appliance breakdown", section_style))
    rows = [
        ["Appliance", "Energy (kWh)", f"Cost ({symbol})", "Runtime (h)", "Share"]
    ]
    for row in report["appliances"]:
        rows.append(
            [
                row["name"],
                f"{row['energy_kwh']:.3f}",
                f"{row['cost_inr']:,.2f}",
                f"{row['runtime_s'] / 3600.0:.2f}",
                f"{row['share'] * 100.0:.1f}%",
            ]
        )
    if len(rows) == 1:
        rows.append(["No data recorded for this period", "", "", "", ""])

    table = Table(rows, colWidths=[52 * mm, 28 * mm, 28 * mm, 28 * mm, 22 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    if report.get("daily"):
        story.append(Paragraph("Daily consumption", section_style))
        daily_rows = [["Day", "Energy (kWh)", f"Cost ({symbol})"]]
        for row in report["daily"][-14:]:
            daily_rows.append(
                [str(row["day"]), f"{row['energy_kwh']:.3f}", f"{row['cost_inr']:,.2f}"]
            )
        daily_table = Table(daily_rows, colWidths=[52 * mm, 40 * mm, 40 * mm])
        daily_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ]
            )
        )
        story.append(daily_table)

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Appliance-level figures are produced by non-intrusive load "
            "monitoring: a single current measurement at the mains is "
            "disaggregated by a MobileNetV3-derived classifier and a "
            "non-negative harmonic least-squares solver. They are estimates, "
            "not sub-metered measurements.",
            subtitle_style,
        )
    )

    document.build(story)
    return path

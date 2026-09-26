import os
import sys
import smtplib
from collections import defaultdict, deque
from datetime import datetime, timedelta
from email.message import EmailMessage
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.utils import get_column_letter

# Load the same .env used by INOUTX.
try:
    from dotenv import load_dotenv
    FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(FRONTEND_DIR, ".env"), override=True)
except Exception:
    FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Reuse the existing INOUTX MongoDB/report logic.
if FRONTEND_DIR not in sys.path:
    sys.path.insert(0, FRONTEND_DIR)

from app import fetch_report_rows, get_report_period, college_buses  # noqa: E402

SENDER = "inoutx.testing@gmail.com"
RECIPIENT = "afridimohamed.cs25@krct.ac.in"
REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "09:30")
REPORT_HOUR = 9
REPORT_MINUTE = 30

THIN = Side(style="thin", color="D9E1F2")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
NAVY = "123B68"
BLUE = "D9EAF7"
GREEN = "E2F0D9"
RED = "FCE4D6"
YELLOW = "FFF2CC"
GREY = "F2F2F2"
WHITE = "FFFFFF"


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def bus_key(row):
    bus_no = clean(row.get("bus_no", row.get("bus_number", "")))
    plate = clean(row.get("plate", ""))
    bus_id = clean(row.get("bus_id", ""))
    return bus_no.upper() or plate.upper() or bus_id.upper() or str(row.get("_id", "UNKNOWN"))


def movement_direction(row):
    value = clean(row.get("status", row.get("direction", row.get("action", "")))).upper()
    if value in {"EXIT", "EXITED", "OUT"}:
        return "EXIT"
    if value in {"ENTRY", "ENTER", "ENTERED", "ARRIVED", "IN"}:
        return "ENTRY"
    return value or "UNKNOWN"


def parse_date_time(row):
    dt = row.get("timestamp") or row.get("datetime") or row.get("created_at") or row.get("entry_datetime")
    if isinstance(dt, datetime):
        return dt

    date_value = clean(row.get("date", ""))
    time_value = clean(row.get("time", row.get("entry_time", "")))
    if not date_value:
        return None

    for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{date_value} {time_value}", fmt)
        except ValueError:
            pass
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_value, fmt)
        except ValueError:
            pass
    return None


def minutes_to_hhmm(minutes):
    if minutes is None:
        return "-"
    minutes = max(0, int(round(minutes)))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_dt(dt):
    return dt.strftime("%H:%M:%S") if isinstance(dt, datetime) else "-"

def entry_timing_status(dt):
    """ENTRY <= 08:45 AM is On Time; after 08:45 AM is Late."""
    if not isinstance(dt, datetime):
        return "-"
    cutoff = dt.replace(hour=8, minute=45, second=0, microsecond=0)
    return "On Time" if dt <= cutoff else "Late"


def sorted_rows(rows):
    def key(row):
        dt = parse_date_time(row)
        return dt or datetime.min
    return sorted(rows, key=key)


def group_rows(rows):
    groups = defaultdict(list)
    for row in sorted_rows(rows):
        groups[bus_key(row)].append(row)
    return groups

def enrich_driver_details(rows):
    """Attach driver details from college_buses to each report row.

    The current INOUTX vehicle registry exposes the driver as the
    ``driver`` field. Optional phone/contact fields are also supported
    when they exist in MongoDB, without changing the database schema.
    """
    try:
        buses = list(college_buses.find({"status": "ACTIVE"}))
    except Exception as exc:
        print("Driver lookup warning:", exc)
        return rows

    by_plate = {}
    by_bus_no = {}
    for bus in buses:
        plate = clean(bus.get("plate", "")).upper()
        bus_no = clean(bus.get("bus_no", bus.get("bus_number", ""))).upper()
        if plate:
            by_plate[plate] = bus
        if bus_no:
            by_bus_no[bus_no] = bus

    enriched = []
    for original in rows:
        row = dict(original)
        plate = clean(row.get("plate", "")).upper()
        bus_no = clean(row.get("bus_no", row.get("bus_number", ""))).upper()
        bus = by_plate.get(plate) or by_bus_no.get(bus_no)

        if bus:
            row["driver"] = clean(
                row.get("driver")
                or bus.get("driver")
                or bus.get("driver_name")
            )
            row["driver_phone"] = clean(
                row.get("driver_phone")
                or bus.get("driver_phone")
                or bus.get("phone")
                or bus.get("contact")
                or bus.get("mobile")
            )
            row["route"] = clean(row.get("route") or bus.get("route"))

        enriched.append(row)

    return enriched




def timing_analysis(rows):
    groups = group_rows(rows)
    result = []

    for key, items in groups.items():
        items = sorted_rows(items)
        bus_no = clean(items[0].get("bus_no", items[0].get("bus_number", ""))) or "-"
        plate = clean(items[0].get("plate", "")) or "-"
        route = clean(items[0].get("route", "")) or "-"
        driver = clean(items[0].get("driver", "")) or "-"
        driver_phone = clean(items[0].get("driver_phone", "")) or "-"

        entries = []
        exits = []
        on_time_entries = 0
        late_entries = 0
        pending_entries = deque()
        stays = []

        for row in items:
            dt = parse_date_time(row)
            direction = movement_direction(row)
            if not dt:
                continue
            if direction == "ENTRY":
                entries.append(dt)
                if entry_timing_status(dt) == "On Time":
                    on_time_entries += 1
                else:
                    late_entries += 1
                pending_entries.append(dt)
            elif direction == "EXIT":
                exits.append(dt)
                if pending_entries:
                    entry_dt = pending_entries.popleft()
                    if dt >= entry_dt:
                        stays.append((dt - entry_dt).total_seconds() / 60)

        result.append({
            "bus_no": bus_no,
            "plate": plate,
            "driver": driver,
            "driver_phone": driver_phone,
            "route": route,
            "detections": len(items),
            "entries": len(entries),
            "on_time_entries": on_time_entries,
            "late_entries": late_entries,
            "exits": len(exits),
            "first_entry": min(entries) if entries else None,
            "last_exit": max(exits) if exits else None,
            "avg_entry": sum((d.hour * 60 + d.minute + d.second / 60) for d in entries) / len(entries) if entries else None,
            "avg_exit": sum((d.hour * 60 + d.minute + d.second / 60) for d in exits) / len(exits) if exits else None,
            "avg_stay": sum(stays) / len(stays) if stays else None,
        })

    return sorted(result, key=lambda x: x["bus_no"])


def write_title(ws, title, subtitle=None, end_col=8):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    c = ws.cell(1, 1, title)
    c.font = Font(size=16, bold=True, color=WHITE)
    c.fill = PatternFill("solid", fgColor=NAVY)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    if subtitle:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=end_col)
        c = ws.cell(2, 1, subtitle)
        c.font = Font(size=10, italic=True, color="666666")
        c.alignment = Alignment(horizontal="center")


def style_header(ws, row, start=1, end=None):
    end = end or ws.max_column
    for col in range(start, end + 1):
        cell = ws.cell(row, col)
        cell.font = Font(bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER


def autosize(ws, max_width=32):
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        length = 0
        for cell in ws[letter]:
            if cell.value is not None:
                length = max(length, len(str(cell.value)))
        ws.column_dimensions[letter].width = min(max(length + 2, 10), max_width)


def entry_timing_status(row):
    """Classify ENTRY detections using the fixed 08:45 AM cutoff.

    ENTRY <= 08:45:00 -> On Time
    ENTRY >  08:45:00 -> Late
    EXIT -> blank / '-'
    """
    if movement_direction(row) != "ENTRY":
        return "-"
    dt = parse_date_time(row)
    if not dt:
        return "-"
    cutoff_minutes = REPORT_HOUR * 60 - 45  # 08:45
    detection_minutes = dt.hour * 60 + dt.minute
    return "On Time" if detection_minutes <= cutoff_minutes else "Late"


def build_workbook(rows, report_date, email_status="Scheduled"):
    """Build the Excel workbook in the exact Vehicle_Monitoring reference style.

    Sheets intentionally follow the reference workbook structure:
      1. Vehicle Log
      2. Daily Summary
      3. Email Report

    Driver details are included directly in Vehicle Log rather than creating
    extra report sheets. MongoDB is not modified.
    """
    wb = Workbook()
    vehicle_log = wb.active
    vehicle_log.title = "Vehicle Log"
    daily_summary = wb.create_sheet("Daily Summary")
    email_report = wb.create_sheet("Email Report")

    rows = sorted_rows(rows)

    # ------------------------------------------------------------
    # Resolve driver/vehicle registry once. This keeps the report
    # aligned with the existing college_buses MongoDB collection.
    # ------------------------------------------------------------
    registry = {}
    try:
        for bus in college_buses.find({"status": "ACTIVE"}):
            plate = clean(bus.get("plate", "")).upper()
            bus_no = clean(bus.get("bus_no", bus.get("bus_number", ""))).upper()
            driver_value = bus.get("driver") or bus.get("driver_name") or ""

            if isinstance(driver_value, dict):
                driver_name = clean(
                    driver_value.get("name") or driver_value.get("driver_name")
                )
                driver_phone = clean(
                    driver_value.get("phone")
                    or driver_value.get("mobile")
                    or driver_value.get("contact")
                )
            else:
                driver_name = clean(driver_value)
                driver_phone = clean(
                    bus.get("driver_phone")
                    or bus.get("phone")
                    or bus.get("contact")
                    or bus.get("mobile")
                )

            info = {
                "driver": driver_name or "-",
                "driver_phone": driver_phone or "-",
                "route": clean(bus.get("route")) or "-",
                "status": clean(bus.get("status")) or "-",
            }
            if plate:
                registry[plate] = info
            if bus_no:
                registry[bus_no] = info
    except Exception as exc:
        print("Driver registry warning:", exc)

    def vehicle_info(row):
        plate = clean(row.get("plate", "")).upper()
        bus_no = clean(row.get("bus_no", row.get("bus_number", ""))).upper()
        info = registry.get(plate) or registry.get(bus_no) or {}
        return (
            clean(row.get("driver") or info.get("driver")) or "-",
            clean(row.get("driver_phone") or info.get("driver_phone")) or "-",
            clean(row.get("route") or info.get("route")) or "-",
        )

    # ------------------------------------------------------------
    # Counts used by Daily Summary
    # ------------------------------------------------------------
    entry_rows = [r for r in rows if movement_direction(r) == "ENTRY"]
    exit_rows = [r for r in rows if movement_direction(r) == "EXIT"]
    on_time = sum(1 for r in entry_rows if entry_timing_status(r) == "On Time")
    late = sum(1 for r in entry_rows if entry_timing_status(r) == "Late")

    # ------------------------------------------------------------
    # 1. Vehicle Log - reference format
    # ------------------------------------------------------------
    write_title(
        vehicle_log,
        "Vehicle Log",
        f"INOUTX daily vehicle movement report - {report_date}",
        10,
    )

    vehicle_headers = [
        "Date",
        "Number Plate",
        "Bus No.",
        "Driver Name",
        "Driver Phone",
        "Log Type",
        "Detection Time",
        "Status",
        "Detection",
        "Timing Status",
    ]
    vehicle_log.append([])
    vehicle_log.append(vehicle_headers)
    style_header(vehicle_log, 4, 1, len(vehicle_headers))

    for row in rows:
        dt = parse_date_time(row)
        direction = movement_direction(row)
        driver, driver_phone, route = vehicle_info(row)
        timing_status = entry_timing_status(row)

        date_text = clean(row.get("date", ""))
        if not date_text and dt:
            date_text = dt.strftime("%d-%m-%Y")

        time_text = clean(row.get("time", ""))
        if not time_text and dt:
            time_text = dt.strftime("%H:%M:%S")

        plate = clean(row.get("plate", "")) or "-"
        bus_no = clean(row.get("bus_no", row.get("bus_number", ""))) or "-"
        detection = clean(
            row.get("detection")
            or row.get("image")
            or row.get("image_path")
            or row.get("ocr_plate")
        ) or "Detected"

        # Keep the reference workbook's simple Log Type / Status concept.
        log_type = "Morning Entry" if direction == "ENTRY" else "Evening Exit" if direction == "EXIT" else direction
        status = timing_status if direction == "ENTRY" else "Detected"

        vehicle_log.append([
            date_text or "-",
            plate,
            bus_no,
            driver,
            driver_phone,
            log_type,
            time_text or "-",
            status,
            detection,
            timing_status,
        ])

    for row in vehicle_log.iter_rows(min_row=5, max_col=10):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Highlight timing status while keeping the reference-style table.
    for r in range(5, vehicle_log.max_row + 1):
        timing_cell = vehicle_log.cell(r, 10)
        if timing_cell.value == "On Time":
            timing_cell.fill = PatternFill("solid", fgColor=GREEN)
        elif timing_cell.value == "Late":
            timing_cell.fill = PatternFill("solid", fgColor=YELLOW)
        direction_cell = vehicle_log.cell(r, 6)
        if direction_cell.value == "Evening Exit":
            direction_cell.fill = PatternFill("solid", fgColor=RED)

    vehicle_log.freeze_panes = "A5"
    autosize(vehicle_log, 30)

    # ------------------------------------------------------------
    # 2. Daily Summary - reference format
    # ------------------------------------------------------------
    write_title(
        daily_summary,
        "Daily Summary",
        f"INOUTX report date: {report_date} | Entry cutoff: 08:45 AM",
        8,
    )
    daily_summary.append([])
    daily_summary.append([
        "Date",
        "Morning Cutoff",
        "Total Morning Entries",
        "On Time",
        "Late",
        "Evening Exits",
        "Total Detections",
        "Email Report Status",
    ])
    style_header(daily_summary, 4, 1, 8)
    daily_summary.append([
        report_date,
        "08:45 AM",
        len(entry_rows),
        on_time,
        late,
        len(exit_rows),
        len(rows),
        email_status,
    ])

    for row in daily_summary.iter_rows(min_row=5, max_col=8):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    daily_summary["D5"].fill = PatternFill("solid", fgColor=GREEN)
    daily_summary["E5"].fill = PatternFill("solid", fgColor=YELLOW)
    daily_summary["F5"].fill = PatternFill("solid", fgColor=RED)
    daily_summary.freeze_panes = "A5"
    autosize(daily_summary, 28)

    # ------------------------------------------------------------
    # 3. Email Report - reference format
    # ------------------------------------------------------------
    write_title(
        email_report,
        "Email Report",
        f"INOUTX automated daily report - {report_date}",
        6,
    )
    email_report.append([])
    email_report.append([
        "Report Date",
        "Recipient",
        "Subject",
        "Attachment",
        "Trigger",
        "Status",
    ])
    style_header(email_report, 4, 1, 6)

    filename = f"INOUTX_Daily_Report_{datetime.now():%Y-%m-%d}.xlsx"
    email_report.append([
        report_date,
        RECIPIENT,
        f"INOUTX Daily Bus Report - {report_date}",
        filename,
        "Daily 09:30 AM",
        email_status,
    ])

    for row in email_report.iter_rows(min_row=5, max_col=6):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    email_report.freeze_panes = "A5"
    autosize(email_report, 42)

    # Workbook presentation.
    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    return wb


def send_email(attachment_bytes, filename, report_date, rows, start_label, end_label):
    smtp_host = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("MAIL_PORT", "465"))
    smtp_username = (os.getenv("MAIL_USERNAME") or os.getenv("GMAIL_USERNAME") or SENDER).strip()
    smtp_password = (os.getenv("MAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or "").strip()
    sender = (os.getenv("MAIL_FROM") or SENDER).strip()

    if sender.lower() != SENDER.lower():
        raise RuntimeError(f"MAIL_FROM must be {SENDER} for this daily report, but is configured as {sender}.")
    if not smtp_password:
        raise RuntimeError("Gmail App Password is missing. Set MAIL_PASSWORD (or GMAIL_APP_PASSWORD) in Frontend/.env.")
    if smtp_username.lower() != SENDER.lower():
        raise RuntimeError(f"MAIL_USERNAME must be {SENDER} for this daily report, but is configured as {smtp_username}.")

    entries = sum(1 for r in rows if movement_direction(r) == "ENTRY")
    exits = sum(1 for r in rows if movement_direction(r) == "EXIT")
    buses = len(group_rows(rows))

    msg = EmailMessage()
    msg["Subject"] = f"INOUTX Daily Bus Report - {report_date}"
    msg["From"] = sender
    msg["To"] = RECIPIENT
    msg.set_content(
        f"INOUTX Daily Bus Report\n\n"
        f"Report window: {start_label} to {end_label}\n"
        f"Unique buses: {buses}\n"
        f"ENTRY detections: {entries}\n"
        f"On Time ENTRY (<= 08:45 AM): {sum(1 for r in rows if movement_direction(r) == "ENTRY" and entry_timing_status(parse_date_time(r)) == "On Time")}\n"
        f"Late ENTRY (> 08:45 AM): {sum(1 for r in rows if movement_direction(r) == "ENTRY" and entry_timing_status(parse_date_time(r)) == "Late")}\n"
        f"EXIT detections: {exits}\n"
        f"Total movement detections: {len(rows)}\n\n"
        f"The attached Excel workbook contains:\n"
        f"- Daily Summary\n"
        f"- Grouped Movement Report\n"
        f"- Bus Timing Analysis\n"
        f"- Visualizations\n\n"
        f"This is an automatically generated IN/OUT X report."
    )
    msg.add_attachment(
        attachment_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
        server.login(smtp_username, smtp_password)
        server.send_message(msg)


def get_daily_report_window(now=None):
    """
    Return the INOUTX daily reporting window.

    Every report is a rolling 24-hour campus window:
        previous day 09:30:00  <= detection < today 09:30:00

    Therefore a report sent at 09:30 AM contains detections from
    yesterday 09:30 AM through today 09:29:59 AM.
    """
    now = now or datetime.now()
    today_0930 = now.replace(
        hour=REPORT_HOUR,
        minute=REPORT_MINUTE,
        second=0,
        microsecond=0
    )

    if now >= today_0930:
        end = today_0930
        start = end - timedelta(days=1)
    else:
        end = today_0930
        start = end - timedelta(days=1)

    return start, end


def generate_and_send():
    now = datetime.now()
    start, end = get_daily_report_window(now)
    rows = fetch_report_rows(start, end)
    rows = enrich_driver_details(rows)
    report_date = now.strftime("%d-%m-%Y")

    wb = build_workbook(rows, report_date)
    output = BytesIO()
    wb.save(output)
    attachment = output.getvalue()

    filename = f"INOUTX_Daily_Report_{now:%Y-%m-%d}.xlsx"
    send_email(attachment, filename, report_date, rows, start.strftime("%d-%m-%Y %I:%M:%S %p"), end.strftime("%d-%m-%Y %I:%M:%S %p"))

    # Keep a local copy for audit/troubleshooting.
    report_dir = os.path.join(FRONTEND_DIR, "daily_reports")
    os.makedirs(report_dir, exist_ok=True)
    local_path = os.path.join(report_dir, filename)
    with open(local_path, "wb") as f:
        f.write(attachment)

    print("=" * 70)
    print("INOUTX DAILY REPORT SENT SUCCESSFULLY")
    print("Date       :", report_date)
    print("Window     :", start.strftime("%d-%m-%Y %I:%M:%S %p"), "to", end.strftime("%d-%m-%Y %I:%M:%S %p"))
    print("Rows       :", len(rows))
    print("Attachment :", local_path)
    print("From       :", SENDER)
    print("To         :", RECIPIENT)
    print("=" * 70)


def main():
    # --test sends immediately. Normal execution is intended for Task Scheduler.
    generate_and_send()


if __name__ == "__main__":
    main()

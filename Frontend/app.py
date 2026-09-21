import sys
import os
import threading
import time
import hashlib
import bcrypt
import jwt
import re
from bson import ObjectId
from datetime import datetime
import secrets
import smtplib
from flask import redirect

from email.message import EmailMessage

from functools import wraps
from flask import session




# =========================================================
# PROJECT ROOT
# =========================================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

sys.path.insert(0, PROJECT_ROOT)

# =========================================================
# IMPORTS
# =========================================================

from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Flask,
    jsonify,
    request,
    send_file,
    send_from_directory
)

from bson import ObjectId

from flask_socketio import SocketIO
from flask_cors import CORS

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image as RLImage,
    KeepTogether
)

from pymongo import (
    DESCENDING,
    ASCENDING
)

# =========================================================
# MONGODB
# =========================================================
from mongodb import (
    db,
    users,
    email_verifications,
    college_buses,
    bus_logs,
    staff_vehicles,
    staff_logs,
    visitor_vehicles,
    visitor_logs,
    unknown_vehicles,
    password_resets,
    alerts,
    detections,
)

# =========================================================
# PATHS
# =========================================================

FRONTEND_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

HTML_DIR = os.path.join(
    FRONTEND_DIR,
    "html"
)

ASSETS_DIR = os.path.join(
    FRONTEND_DIR,
    "assets"
)

DIST_DIR = os.path.join(
    FRONTEND_DIR,
    "dist"
)

REACT_INDEX_FILE = os.path.join(
    DIST_DIR,
    "index.html"
)

INDEX_FILE = os.path.join(
    HTML_DIR,
    "index.html"
)

CAPTURED_FRAMES_DIR = os.path.join(
    PROJECT_ROOT,
    "captured_frames"
)

# =========================================================
# COLLEGE LOGOS
# =========================================================

KRCE_LOGO = os.path.join(
    ASSETS_DIR,
    "krce_logo.png"
)

KRCT_LOGO = os.path.join(
    ASSETS_DIR,
    "krct_logo.png"
)

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "INOUTX_CHANGE_THIS_SECRET_KEY"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

CORS(
    app,
    supports_credentials=True,
    resources={
        r"/api/*": {
            "origins": "*"
        }
    }
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

# =========================================================
# GLOBALS
# =========================================================

CHANGE_STREAM_STARTED = False

EXACT_COLLEGE_EMAIL_DOMAINS = {
    "krct.ac.in",
    "krce.ac.in",
}
configured_college_domains = {
    domain.strip().lower().lstrip("@")
    for domain in os.getenv("COLLEGE_EMAIL_DOMAINS", "").split(",")
    if domain.strip()
}
COLLEGE_EMAIL_DOMAINS = (
    configured_college_domains & EXACT_COLLEGE_EMAIL_DOMAINS
    if configured_college_domains
    else EXACT_COLLEGE_EMAIL_DOMAINS
)
OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_MAX_RESENDS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
# =========================================================
# PASSWORD RESET CONFIGURATION
# =========================================================

RESET_TOKEN_EXPIRY_MINUTES = int(
    os.getenv(
        "RESET_TOKEN_EXPIRY_MINUTES",
        "30"
    )
)

APP_BASE_URL = os.getenv(
    "APP_BASE_URL",
    "http://127.0.0.1:5000"
)
PRIVILEGED_ROLES = {
    "principal",
    "executive_director",
    "hod",
    "hoc",
    "config_admin",
    "gate_watchman",
    "bus_incharge",
}
# =========================================================
# SYSTEM CONFIGURATION ADMIN
# =========================================================

CONFIG_ADMIN_EMAIL = os.getenv(
    "CONFIG_ADMIN_EMAIL",
    ""
).strip().lower()

CONFIG_ADMIN_PASSWORD = os.getenv(
    "CONFIG_ADMIN_PASSWORD",
    ""
)

if not CONFIG_ADMIN_EMAIL or not CONFIG_ADMIN_PASSWORD:
    print(
        "WARNING: System Configuration admin credentials "
        "are not configured in .env"
    )


# =========================================================
# HELPERS
# =========================================================

def serialize_value(value):

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, ObjectId):
        return str(value)

    return value


def serialize_document(document):

    if not document:
        return None

    result = {}

    for key, value in document.items():

        if key == "_id":
            result["_id"] = str(value)

        else:
            result[key] = serialize_value(value)

    return result


def clean_plate(plate):

    if not plate:
        return ""

    return (
        str(plate)
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )


def safe_int(value, default=0):

    try:
        return int(value)

    except (
        TypeError,
        ValueError
    ):
        return default


def normalize_role(value):

    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value or "").strip().lower()
    ).strip("_")


def is_college_email(email):

    if not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[^\s@]+",
        email
    ):
        return False

    domain = email.rsplit("@", 1)[-1].lower()
    return domain in COLLEGE_EMAIL_DOMAINS


def send_verification_otp(email, otp):

    smtp_host = os.getenv("MAIL_SERVER")
    smtp_port = int(os.getenv("MAIL_PORT", "587"))
    smtp_username = os.getenv("MAIL_USERNAME")
    smtp_password = os.getenv("MAIL_PASSWORD")
    sender = os.getenv("MAIL_FROM")

    if not all((smtp_host, smtp_username, smtp_password, sender)):
        raise RuntimeError(
            "Email delivery is not configured. Set MAIL_SERVER, MAIL_PORT, "
            "MAIL_USERNAME, MAIL_PASSWORD, and MAIL_FROM."
        )

    message = EmailMessage()
    message["Subject"] = "INOUTX college email verification"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Your INOUTX verification code is "
        f"{otp}. It expires in {OTP_EXPIRY_MINUTES} minutes."
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(message)
# =========================================================
# PASSWORD RESET EMAIL
# =========================================================

def send_password_reset_email(
    email,
    reset_link
):
    """
    Send password reset link using
    the existing INOUTX SMTP configuration.
    """

    smtp_host = os.getenv(
        "MAIL_SERVER"
    )

    smtp_port = int(
        os.getenv(
            "MAIL_PORT",
            "587"
        )
    )

    smtp_username = os.getenv(
        "MAIL_USERNAME"
    )

    smtp_password = os.getenv(
        "MAIL_PASSWORD"
    )

    sender = os.getenv(
        "MAIL_FROM"
    )

    if not all((
        smtp_host,
        smtp_username,
        smtp_password,
        sender
    )):
        raise RuntimeError(
            "Email delivery is not configured. "
            "Set MAIL_SERVER, MAIL_PORT, "
            "MAIL_USERNAME, MAIL_PASSWORD, "
            "and MAIL_FROM."
        )

    message = EmailMessage()

    message["Subject"] = (
        "INOUTX Password Reset"
    )

    message["From"] = sender

    message["To"] = email

    message.set_content(
        "INOUTX Password Reset\n\n"

        "We received a request to reset "
        "the password for your INOUTX account.\n\n"

        "Click the link below to create "
        "a new password:\n\n"

        f"{reset_link}\n\n"

        f"This link expires in "
        f"{RESET_TOKEN_EXPIRY_MINUTES} minutes "
        "and can only be used once.\n\n"

        "If you did not request a password reset, "
        "you can safely ignore this email.\n\n"

        "INOUTX\n"
        "Department Of CSE - KRCT"
    )

    with smtplib.SMTP(
        smtp_host,
        smtp_port,
        timeout=15
    ) as server:

        server.starttls()

        server.login(
            smtp_username,
            smtp_password
        )

        server.send_message(
            message
        )
# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route(
    "/api/forgot-password",
    methods=["POST"]
)
def forgot_password():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        email = str(
            data.get(
                "email",
                ""
            )
        ).strip().lower()

        if not email:

            return jsonify({
                "success": False,
                "error": "Email is required."
            }), 400

        if not is_college_email(email):

            return jsonify({
                "success": False,
                "error": "Use your official college email address."
            }), 400

        # -------------------------------------------------
        # Find verified user
        # -------------------------------------------------

        user = users.find_one({
            "email": email,
            "email_verified": True
        })

        # -------------------------------------------------
        # Generic response
        #
        # Do not reveal whether an email exists.
        # -------------------------------------------------

        generic_response = jsonify({
            "success": True,
            "message": (
                "If an account exists for this email, "
                "a password reset link has been sent."
            )
        })

        if not user:
            return generic_response, 200

        # -------------------------------------------------
        # Remove previous reset tokens
        # -------------------------------------------------

        password_resets.delete_many({
            "user_id": user["_id"]
        })

        # -------------------------------------------------
        # Generate secure random token
        # -------------------------------------------------

        raw_token = secrets.token_urlsafe(
            48
        )

        token_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        now = datetime.now()

        expires_at = (
            now
            + timedelta(
                minutes=RESET_TOKEN_EXPIRY_MINUTES
            )
        )

        # -------------------------------------------------
        # Save only token hash
        # -------------------------------------------------

        password_resets.insert_one({

            "user_id":
                user["_id"],

            "email":
                email,

            "token_hash":
                token_hash,

            "created_at":
                now,

            "expires_at":
                expires_at,

            "used":
                False

        })

        # -------------------------------------------------
        # Create reset URL
        # -------------------------------------------------

        reset_link = (
            APP_BASE_URL.rstrip("/")
            + "/reset-password.html?token="
            + raw_token
        )

        # -------------------------------------------------
        # Send email
        # -------------------------------------------------

        try:

            send_password_reset_email(
                email,
                reset_link
            )

        except Exception as email_error:

            # Remove token if email failed
            password_resets.delete_one({
                "token_hash":
                    token_hash
            })

            print(
                "Password reset email error:",
                repr(email_error)
            )

            return jsonify({
                "success": False,
                "error": (
                    "We couldn't send the password "
                    "reset email. Please try again."
                )
            }), 502

        print(
            "Password reset email sent to:",
            email
        )

        return generic_response, 200

    except Exception as e:

        print(
            "Forgot password error:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to process the password "
                "reset request."
            )
        }), 500
# =========================================================
# RESET PASSWORD
# =========================================================

@app.route(
    "/api/reset-password",
    methods=["POST"]
)
def reset_password():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        token = str(
            data.get(
                "token",
                ""
            )
        ).strip()

        password = str(
            data.get(
                "password",
                ""
            )
        )

        confirm_password = str(
            data.get(
                "confirm_password",
                data.get(
                    "confirmPassword",
                    ""
                )
            )
        )

        # -------------------------------------------------
        # Validate token
        # -------------------------------------------------

        if not token:

            return jsonify({
                "success": False,
                "error": (
                    "Password reset token is required."
                )
            }), 400

        # -------------------------------------------------
        # Validate password
        # -------------------------------------------------

        if len(password) < 6:

            return jsonify({
                "success": False,
                "error": (
                    "Password must contain at least "
                    "6 characters."
                )
            }), 400

        if password != confirm_password:

            return jsonify({
                "success": False,
                "error": (
                    "Passwords do not match."
                )
            }), 400

        # -------------------------------------------------
        # Hash supplied token
        # -------------------------------------------------

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        # -------------------------------------------------
        # Find valid reset token
        # -------------------------------------------------

        reset_record = password_resets.find_one({
            "token_hash":
                token_hash,

            "used":
                False
        })

        if not reset_record:

            return jsonify({
                "success": False,
                "error": (
                    "This password reset link is "
                    "invalid or has already been used."
                )
            }), 400

        # -------------------------------------------------
        # Check expiration
        # -------------------------------------------------

        expires_at = reset_record.get(
            "expires_at"
        )

        if (
            not expires_at
            or expires_at < datetime.now()
        ):

            password_resets.delete_one({
                "_id":
                    reset_record["_id"]
            })

            return jsonify({
                "success": False,
                "error": (
                    "This password reset link has expired. "
                    "Please request a new one."
                )
            }), 400

        # -------------------------------------------------
        # Find user
        # -------------------------------------------------

        user = users.find_one({
            "_id":
                reset_record["user_id"]
        })

        if not user:

            password_resets.delete_one({
                "_id":
                    reset_record["_id"]
            })

            return jsonify({
                "success": False,
                "error":
                    "User account was not found."
            }), 404

        # -------------------------------------------------
        # Hash new password using bcrypt
        # -------------------------------------------------

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # -------------------------------------------------
        # Update password
        # -------------------------------------------------

        result = users.update_one(

            {
                "_id":
                    user["_id"]
            },

            {
                "$set": {

                    "password":
                        hashed_password,

                    "updated_at":
                        datetime.now()

                }
            }
        )

        if result.matched_count != 1:

            return jsonify({
                "success": False,
                "error": (
                    "Unable to update the password."
                )
            }), 500

        # -------------------------------------------------
        # Delete used reset token
        # -------------------------------------------------

        password_resets.delete_one({
            "_id":
                reset_record["_id"]
        })

        # -------------------------------------------------
        # Delete all other reset tokens
        # -------------------------------------------------

        password_resets.delete_many({
            "user_id":
                user["_id"]
        })

        # -------------------------------------------------
        # Clear existing login session
        # -------------------------------------------------

        session.clear()

        return jsonify({

            "success":
                True,

            "message":
                (
                    "Password reset successfully. "
                    "You can now log in with your new password."
                )

        }), 200

    except Exception as e:

        print(
            "Reset password error:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to reset the password."
            )
        }), 500

def build_safe_user(user):

    return {
        "id": str(user.get("_id")),
        "name": str(user.get("name") or "").strip(),
        "email": str(user.get("email") or "").strip(),
        "role": str(user.get("role") or "").strip(),
        "active": user.get("active") is True,
        "email_verified": user.get("email_verified") is True,
    }


# =========================================================
# DATE HELPERS
# =========================================================

def parse_date_value(value):
    """
    Supports:

    DD-MM-YYYY
    YYYY-MM-DD
    DD/MM/YYYY
    YYYY/MM/DD
    ISO datetime
    Python datetime
    """

    if not value:
        return None

    if isinstance(value, datetime):
        return value

    value = str(value).strip()

    formats = [
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]

    for fmt in formats:

        try:

            return datetime.strptime(
                value,
                fmt
            )

        except ValueError:
            pass

    try:

        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00"
            )
        )

        # Convert timezone-aware datetime to naive datetime
        if parsed.tzinfo is not None:

            parsed = parsed.replace(
                tzinfo=None
            )

        return parsed

    except Exception:
        return None


def get_log_datetime(row):
    """
    Obtain the best available datetime from a log.
    """

    possible_datetime_fields = [
        "timestamp",
        "created_at",
        "entry_datetime",
        "exit_datetime",
        "datetime"
    ]

    for field in possible_datetime_fields:

        value = row.get(field)

        parsed = parse_date_value(value)

        if parsed:
            return parsed

    date_value = row.get("date")

    time_value = row.get(
        "time",
        "00:00:00"
    )

    if date_value:

        date_parsed = parse_date_value(
            date_value
        )

        if date_parsed:

            time_string = str(
                time_value or "00:00:00"
            ).strip()

            for time_format in [
                "%H:%M:%S",
                "%H:%M"
            ]:

                try:

                    parsed_time = datetime.strptime(
                        time_string,
                        time_format
                    ).time()

                    return datetime.combine(
                        date_parsed.date(),
                        parsed_time
                    )

                except ValueError:
                    pass

            return date_parsed

    return None


def fetch_report_rows(
    start_datetime=None,
    end_datetime=None
):
    """
    Fetch bus logs and perform date filtering in Python.

    This avoids problems caused by storing dates as
    DD-MM-YYYY strings in MongoDB.
    """

    logs = (
        bus_logs.find()
        .sort(
            "_id",
            DESCENDING
        )
    )

    rows = []

    for row in logs:

        log_datetime = get_log_datetime(
            row
        )

        if start_datetime:

            if not log_datetime:
                continue

            if log_datetime < start_datetime:
                continue

        if end_datetime:

            if not log_datetime:
                continue

            if log_datetime >= end_datetime:
                continue

        rows.append(row)

    return rows


def get_report_period(period):
    """
    Returns:

        today
        weekly = today + previous 6 days
        monthly = current month
    """

    now = datetime.now()

    period = str(
        period or ""
    ).strip().lower()

    if period == "today":

        start = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        end = start + timedelta(
            days=1
        )

        return start, end

    if period == "weekly":

        start = (
            now - timedelta(days=6)
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        end = now + timedelta(
            seconds=1
        )

        return start, end

    if period == "monthly":

        start = now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        end = now + timedelta(
            seconds=1
        )

        return start, end

    return None, None


def resolve_captured_image(image_value):
    """
    Convert a database image value into an actual
    captured image path.

    Supports:

        filename.jpg
        /captured-frames/filename.jpg
        Windows paths
        Linux paths
        URL-like paths
    """

    if not image_value:
        return None

    try:

        raw = str(
            image_value
        ).strip()

        if not raw:
            return None

        # Remove query string
        raw = raw.split(
            "?",
            1
        )[0]

        # Normalize separators
        raw = raw.replace(
            "\\",
            "/"
        )

        filename = os.path.basename(
            raw
        )

        if not filename:
            return None

        candidate = os.path.join(
            CAPTURED_FRAMES_DIR,
            filename
        )

        if os.path.isfile(candidate):

            return candidate

    except Exception as e:

        print(
            "Image resolve error:",
            e
        )

    return None


# =========================================================
# PDF HELPERS
# =========================================================

def create_logo(
    logo_path,
    max_width_mm,
    max_height_mm
):
    """
    Create a ReportLab image while preserving
    its aspect ratio.
    """

    if not logo_path:
        return None

    if not os.path.isfile(logo_path):
        return None

    try:

        image = RLImage(
            logo_path
        )

        image._restrictSize(
            max_width_mm * mm,
            max_height_mm * mm
        )

        return image

    except Exception as e:

        print(
            "Logo loading error:",
            logo_path,
            e
        )

        return None


def create_captured_image(
    image_path,
    max_width_mm=42,
    max_height_mm=30
):
    """
    Create a captured vehicle image while preserving
    its original aspect ratio.
    """

    if not image_path:
        return None

    if not os.path.isfile(image_path):
        return None

    try:

        image = RLImage(
            image_path
        )

        image._restrictSize(
            max_width_mm * mm,
            max_height_mm * mm
        )

        return image

    except Exception as e:

        print(
            "Captured image error:",
            e
        )

        return None


def build_pdf_header(
    report_title,
    total_records
):
    """
    Build professional A4 PDF header.

    KRCE logo  -> left
    Title      -> center
    KRCT logo  -> right
    """

    krce = create_logo(
        KRCE_LOGO,
        48,
        27
    )

    krct = create_logo(
        KRCT_LOGO,
        48,
        27
    )

    title_style = ParagraphStyle(
        "PDFHeaderTitle",
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor(
            "#123B68"
        ),
        spaceAfter=2 * mm
    )

    subtitle_style = ParagraphStyle(
        "PDFHeaderSubtitle",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor(
            "#374151"
        )
    )

    meta_style = ParagraphStyle(
        "PDFHeaderMeta",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor(
            "#6B7280"
        )
    )

    center_content = [

        Paragraph(
            "IN/OUT X",
            title_style
        ),

        Paragraph(
            "VEHICLE MONITORING SYSTEM",
            subtitle_style
        ),

        Spacer(
            1,
            1.5 * mm
        ),

        Paragraph(
            report_title,
            subtitle_style
        ),

        Spacer(
            1,
            1.5 * mm
        ),

        Paragraph(
            (
                "Generated: "
                +
                datetime.now().strftime(
                    "%d-%m-%Y %H:%M:%S"
                )
                +
                " &nbsp;&nbsp;|&nbsp;&nbsp; "
                "Total Records: "
                +
                str(total_records)
            ),
            meta_style
        )

    ]

    if not krce:

        krce = Paragraph(
            "KRCE",
            subtitle_style
        )

    if not krct:

        krct = Paragraph(
            "KRCT",
            subtitle_style
        )

    header = Table(

        [[
            krce,
            center_content,
            krct
        ]],

        colWidths=[
            52 * mm,
            96 * mm,
            52 * mm
        ],

        rowHeights=[
            32 * mm
        ]

    )

    header.setStyle(
        TableStyle([

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),

            (
                "ALIGN",
                (0, 0),
                (0, 0),
                "LEFT"
            ),

            (
                "ALIGN",
                (1, 0),
                (1, 0),
                "CENTER"
            ),

            (
                "ALIGN",
                (2, 0),
                (2, 0),
                "RIGHT"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                1 * mm
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                1 * mm
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                1 * mm
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                1 * mm
            ),

            (
                "LINEBELOW",
                (0, 0),
                (-1, -1),
                1.2,
                colors.HexColor(
                    "#123B68"
                )
            )

        ])
    )

    return header


def pdf_footer(
    canvas,
    document
):
    """
    Footer for every A4 PDF page.
    """

    canvas.saveState()

    page_width, page_height = A4

    footer_y = 8 * mm

    canvas.setStrokeColor(
        colors.HexColor(
            "#D1D5DB"
        )
    )

    canvas.setLineWidth(
        0.5
    )

    canvas.line(
        12 * mm,
        footer_y + 5 * mm,
        page_width - 12 * mm,
        footer_y + 5 * mm
    )

    canvas.setFont(
        "Helvetica",
        7
    )

    canvas.setFillColor(
        colors.HexColor(
            "#6B7280"
        )
    )

    canvas.drawString(
        12 * mm,
        footer_y,
        "IN/OUT X - Vehicle Monitoring System"
    )

    canvas.drawRightString(
        page_width - 12 * mm,
        footer_y,
        f"Page {canvas.getPageNumber()}"
    )

    canvas.restoreState()


# =========================================================
# MONGODB CONNECTION CHECK
# =========================================================

def check_mongodb():

    try:

        result = db.command(
            "ping"
        )

        print()
        print("=" * 60)
        print("MONGODB CONNECTION")
        print("=" * 60)
        print("Status        : CONNECTED")
        print("Database      :", db.name)
        print("Ping          :", result)
        print("College buses :", college_buses.name)
        print("Staff vehicles:", staff_vehicles.name)
        print("Captured dir  :", CAPTURED_FRAMES_DIR)
        print("=" * 60)
        print()

        return True

    except Exception as e:

        print()
        print("=" * 60)
        print("MONGODB CONNECTION ERROR")
        print("=" * 60)
        print(str(e))
        print("=" * 60)
        print()

        return False


# =========================================================
# AUTHENTICATION
# =========================================================

def login_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if "user" not in session:

            return jsonify({
                "success": False,
                "error": "Authentication required."
            }), 401

        return function(
            *args,
            **kwargs
        )

    return decorated_function


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/api/login",
    methods=["POST"]
)
def login():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        email = str(
            data.get(
                "email",
                ""
            )
        ).strip().lower()

        password = str(
            data.get(
                "password",
                ""
            )
        )

        if not email or not password:

            return jsonify({
                "success": False,
                "error": (
                    "Email and password are required."
                )
            }), 400

        user = users.find_one({
            "email": email
        })

        if not user:

            return jsonify({
                "success": False,
                "error": (
                    "Invalid email or password."
                )
            }), 401

        if user.get("email_verified") is not True:

            return jsonify({
                "success": False,
                "error": "Verify your college email before logging in.",
                "email_verification_required": True
            }), 403

        if not user.get(
            "active",
            False
        ):

            return jsonify({
                "success": False,
                "error": (
                    "This account is inactive."
                )
            }), 403

        stored_password = user.get(
            "password"
        )

        if not stored_password:

            return jsonify({
                "success": False,
                "error": (
                    "Account password is not configured."
                )
            }), 500

        if isinstance(
            stored_password,
            bytes
        ):

            password_hash = stored_password

        else:

            password_hash = str(
                stored_password
            ).encode(
                "utf-8"
            )

        password_valid = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash
        )

        if not password_valid:

            return jsonify({
                "success": False,
                "error": (
                    "Invalid email or password."
                )
            }), 401

        session["user"] = {

            "id":
                str(user["_id"]),

            "name":
                user.get(
                    "name",
                    ""
                ),

            "email":
                user.get(
                    "email",
                    ""
                ),

            "role":
                user.get("role", ""),

            "active":
                user.get("active") is True,

            "email_verified": True

        }

        session.permanent = True
        print("LOGIN SESSION CREATED:")
        print(session.get("user"))

        return jsonify({

            "success":
                True,

            "message":
                "Login successful.",

            "user":
                session["user"]

        })

    except Exception as e:

        print(
            "Login error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# SYSTEM CONFIGURATION ACCESS CHECK
# =========================================================

@app.route(
    "/api/config-access",
    methods=["GET"]
)
def config_access():

    try:

        user = session.get("user")

        if not user:

            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Login required."
            }), 401

        logged_in_email = str(
            user.get(
                "email",
                ""
            )
        ).strip().lower()

        logged_in_role = str(
            user.get(
                "role",
                ""
            )
        ).strip().lower()

        if (
            not CONFIG_ADMIN_EMAIL
            or logged_in_email != CONFIG_ADMIN_EMAIL
            or logged_in_role != "config_admin"
        ):

            return jsonify({
                "success": False,
                "authorized": False,
                "error": (
                    "You are not authorized to access "
                    "System Configuration."
                )
            }), 403

        return jsonify({
            "success": True,
            "authorized": True,
            "email": logged_in_email,
            "role": logged_in_role
        })

    except Exception as e:

        print(
            "Config access check error:",
            e
        )

        return jsonify({
            "success": False,
            "authorized": False,
            "error": str(e)
        }), 500
# REGISTER USER
# =========================================================

@app.route(
    "/api/register",
    methods=["POST"]
)
def register():

    try:

        data = request.get_json(silent=True) or {}

        name = str(
            data.get("name", data.get("full_name", ""))
        ).strip()

        email = str(
            data.get("email", "")
        ).strip().lower()

        phone = str(
            data.get("phone", "")
        ).strip()

        password = str(
            data.get("password", "")
        )

        confirm_password = str(
            data.get("confirm_password", data.get("confirmPassword", ""))
        )

        role = normalize_role(
            data.get("account_type", data.get("accountType", data.get("role")))
        )

        if not name:
            return jsonify({
                "success": False,
                "error": "Name is required."
            }), 400

        if len(name) > 100:
            return jsonify({
                "success": False,
                "error": "Name must not exceed 100 characters."
            }), 400

        if not is_college_email(email):
            return jsonify({
                "success": False,
                "error": "Use an official college email address."
            }), 400

        if len(email) > 254:
            return jsonify({
                "success": False,
                "error": "Email address is too long."
            }), 400

        if not re.fullmatch(r"[0-9+() .-]{7,20}", phone):
            return jsonify({
                "success": False,
                "error": "Please enter a valid phone number."
            }), 400

        if len(password) < 6:
            return jsonify({
                "success": False,
                "error": "Password must contain at least 6 characters."
            }), 400

        if not confirm_password:
            return jsonify({
        "success": False,
        "error": "Please confirm your password."
    }), 400

        if password != confirm_password:
            return jsonify({
                "success": False,
                "error": "Passwords do not match."
            }), 400

        if not role:
            return jsonify({
                "success": False,
                "error": "Account type is required."
            }), 400

        existing_user = users.find_one({"email": email})

        if existing_user and (
            existing_user.get("email_verified") is True
            or existing_user.get("active") is True
        ):
            return jsonify({
                "success": False,
                "error": "An account with this email already exists."
            }), 409

        if existing_user:
            users.delete_one({"_id": existing_user["_id"]})

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        otp = str(secrets.randbelow(900000) + 100000)
        now = datetime.now()
        pending_registration = {
            "name": name,
            "email": email,
            "phone": phone,
            "password": hashed_password,
            "role": role,
            "otp_hash": bcrypt.hashpw(
                otp.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8"),
            "otp_expires_at": now + timedelta(minutes=OTP_EXPIRY_MINUTES),
            "attempts": 0,
            "resend_count": 0,
            "last_sent_at": now,
            "created_at": now,
        }

        email_verifications.replace_one(
            {"email": email},
            pending_registration,
            upsert=True
        )

        try:
            send_verification_otp(email, otp)
        except Exception as email_error:
            email_verifications.delete_one({"email": email})
            print("Registration email delivery error:", repr(email_error))
            return jsonify({
                "success": False,
                "error": f"Email error: {str(email_error)}"
            }), 502

        return jsonify({
            "success": True,
            "message": "Verification code sent to your email."
        }), 201

    except Exception as e:

        print("Register error:", e)

        return jsonify({
            "success": False,
            "error": "Unable to create the account."
        }), 500


@app.route(
    "/api/verify-email",
    methods=["POST"]
)
def verify_email():

    try:
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        otp = str(data.get("otp", "")).strip()

        pending = email_verifications.find_one({"email": email})

        if not pending:
            return jsonify({
                "success": False,
                "error": "Invalid verification request."
            }), 400

        if pending.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
            return jsonify({
                "success": False,
                "error": "Too many verification attempts. Please wait before requesting another code."
            }), 429

        email_verifications.update_one(
            {"_id": pending["_id"]},
            {"$inc": {"attempts": 1}}
        )

        if pending.get("otp_expires_at") and pending["otp_expires_at"] < datetime.now():
            return jsonify({
                "success": False,
                "error": "Verification code expired. Please request a new code."
            }), 400

        stored_otp_hash = str(pending.get("otp_hash") or "").encode("utf-8")
        if (
            not otp.isdigit()
            or len(otp) != 6
            or not stored_otp_hash
            or not bcrypt.checkpw(otp.encode("utf-8"), stored_otp_hash)
        ):
            return jsonify({
                "success": False,
                "error": "Invalid verification code."
            }), 400

        role = normalize_role(pending.get("role"))
        active = role not in PRIVILEGED_ROLES

        user_document = {
            "name": pending["name"],
            "email": pending["email"],
            "phone": pending["phone"],
            "password": pending["password"],
            "role": role,
            "active": active,
            "email_verified": True,
            "email_verified_at": datetime.now(),
            "created_at": pending.get("created_at", datetime.now()),
        }

        users.insert_one(user_document)
        email_verifications.delete_one({"_id": pending["_id"]})

        return jsonify({
            "success": True,
            "message": (
                "Email verified. Your account is ready to use."
                if active else
                "Email verified. Your account is awaiting role approval."
            )
        })

    except Exception as e:
        print("Email verification error:", e)
        return jsonify({
            "success": False,
            "error": "Unable to verify the email address."
        }), 500


@app.route(
    "/api/resend-otp",
    methods=["POST"]
)
def resend_otp():

    try:
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        pending = email_verifications.find_one({"email": email})

        if not pending:
            return jsonify({
                "success": False,
                "error": "Invalid verification request."
            }), 400

        now = datetime.now()
        last_sent_at = pending.get("last_sent_at")

        if (
            last_sent_at
            and (now - last_sent_at).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS
        ) or pending.get("resend_count", 0) >= OTP_MAX_RESENDS:
            return jsonify({
                "success": False,
                "error": "Too many verification attempts. Please wait before requesting another code."
            }), 429

        otp = str(secrets.randbelow(900000) + 100000)
        email_verifications.update_one(
            {"_id": pending["_id"]},
            {
                "$set": {
                    "otp_hash": bcrypt.hashpw(
                        otp.encode("utf-8"),
                        bcrypt.gensalt()
                    ).decode("utf-8"),
                    "otp_expires_at": now + timedelta(minutes=OTP_EXPIRY_MINUTES),
                    "attempts": 0,
                    "last_sent_at": now,
                },
                "$inc": {"resend_count": 1}
            }
        )

        try:
            send_verification_otp(email, otp)
        except Exception as email_error:
            print("Resend email delivery error:", repr(email_error))
            return jsonify({
                "success": False,
                "error": "We couldn't send the verification code. Please try again."
            }), 502

        return jsonify({
            "success": True,
            "message": "Verification code sent to your email."
        })

    except Exception as e:
        print("Resend OTP error:", repr(e))
        return jsonify({
            "success": False,
            "error": "We couldn't send the verification code. Please try again."
        }), 500


# =========================================================
# CURRENT USER
# =========================================================

@app.route(
    "/api/me",
    methods=["GET"]
)
def current_user():

    user = session.get(
        "user"
    )

    if not user:

        return jsonify({
            "authenticated": False
        }), 401

    return jsonify({

        "success":
            True,

        "authenticated":
            True,

        "user":
            user

    })


# =========================================================
# PROFILE - GET CURRENT USER FROM MONGODB
# =========================================================

@app.route(
    "/api/profile",
    methods=["GET"]
)
@login_required
def get_profile():

    try:

        session_user = session.get("user") or {}
        user_id = session_user.get("id")

        if not user_id:
            return jsonify({
                "success": False,
                "error": "User session is invalid."
            }), 401

        try:
            object_id = ObjectId(user_id)
        except Exception:
            return jsonify({
                "success": False,
                "error": "Invalid user account identifier."
            }), 401

        user = users.find_one({"_id": object_id})

        if not user:
            session.clear()
            return jsonify({
                "success": False,
                "error": "User account was not found."
            }), 401

        safe_user = build_safe_user(user)

        # Keep the session synchronized with MongoDB.
        session["user"] = safe_user

        return jsonify({
            "success": True,
            "user": safe_user
        })

    except Exception as e:

        print("Get profile error:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================================================
# PROFILE - UPDATE CURRENT USER
# =========================================================

@app.route(
    "/api/profile",
    methods=["PUT"]
)
@login_required
def update_profile():

    try:

        data = request.get_json(silent=True) or {}
        session_user = session.get("user") or {}
        user_id = session_user.get("id")

        if not user_id:
            return jsonify({
                "success": False,
                "error": "User session is invalid."
            }), 401

        try:
            object_id = ObjectId(user_id)
        except Exception:
            return jsonify({
                "success": False,
                "error": "Invalid user account identifier."
            }), 401

        current_user_doc = users.find_one({"_id": object_id})

        if not current_user_doc:
            session.clear()
            return jsonify({
                "success": False,
                "error": "User account was not found."
            }), 401

        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        new_password = str(data.get("password", ""))

        if email != str(current_user_doc.get("email") or "").strip().lower():
            return jsonify({
                "success": False,
                "error": "Email changes require a new college email verification."
            }), 400

        if not name:
            return jsonify({
                "success": False,
                "error": "Full name is required."
            }), 400

        if len(name) > 100:
            return jsonify({
                "success": False,
                "error": "Full name is too long."
            }), 400

        if not email or "@" not in email:
            return jsonify({
                "success": False,
                "error": "A valid email address is required."
            }), 400

        if len(email) > 254:
            return jsonify({
                "success": False,
                "error": "Email address is too long."
            }), 400

        if new_password and len(new_password) < 6:
            return jsonify({
                "success": False,
                "error": "New password must contain at least 6 characters."
            }), 400

        existing_email = users.find_one({
            "email": email,
            "_id": {"$ne": object_id}
        })

        if existing_email:
            return jsonify({
                "success": False,
                "error": "That email address is already in use."
            }), 409

        update_fields = {
            "name": name,
            "email": email,
            "updated_at": datetime.now()
        }

        if new_password:
            update_fields["password"] = bcrypt.hashpw(
                new_password.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")

        result = users.update_one(
            {"_id": object_id},
            {"$set": update_fields}
        )

        if result.matched_count != 1:
            return jsonify({
                "success": False,
                "error": "Unable to update the user account."
            }), 500

        updated_user = users.find_one({"_id": object_id})

        if not updated_user:
            return jsonify({
                "success": False,
                "error": "Updated user account could not be loaded."
            }), 500

        safe_user = build_safe_user(updated_user)

        session["user"] = safe_user
        session.modified = True

        return jsonify({
            "success": True,
            "message": "Profile updated successfully.",
            "user": safe_user
        })

    except Exception as e:

        print("Update profile error:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================================================
# LOGOUT
# =========================================================

@app.route(
    "/api/logout",
    methods=["POST"]
)
def logout():

    session.clear()

    return jsonify({

        "success":
            True,

        "message":
            "Logged out successfully."

    })


# =========================================================
# CREATE INDEXES
# =========================================================

def ensure_indexes():

    try:

        # =====================================================
        # USERS INDEX
        # =====================================================

        try:

            users.create_index(
                [("email", ASCENDING)],
                name="users_email_unique_idx",
                unique=True
            )

        except Exception as index_error:

            print(
                "Users index warning:",
                index_error
            )


        # =====================================================
        # EMAIL VERIFICATION INDEX
        # =====================================================

        try:

            email_verifications.create_index(
                [("email", ASCENDING)],
                name="email_verifications_email_unique_idx",
                unique=True
            )

        except Exception as index_error:

            print(
                "Email verification index warning:",
                index_error
            )


        # =====================================================
        # PASSWORD RESET TOKEN INDEXES
        # =====================================================

        try:

            # Each reset token must be unique
            password_resets.create_index(
                [("token_hash", ASCENDING)],
                name="password_resets_token_idx",
                unique=True
            )

            # Automatically remove expired reset tokens
            password_resets.create_index(
                [("expires_at", ASCENDING)],
                name="password_resets_expiry_idx",
                expireAfterSeconds=0
            )

        except Exception as index_error:

            print(
                "Password reset index warning:",
                index_error
            )


        # =====================================================
        # COLLEGE BUS INDEXES
        # =====================================================

        college_buses.create_index(
            [("plate", ASCENDING)],
            name="college_buses_plate_idx"
        )

        college_buses.create_index(
            [("bus_no", ASCENDING)],
            name="college_buses_bus_no_idx"
        )

        college_buses.create_index(
            [("status", ASCENDING)],
            name="college_buses_status_idx"
        )

        college_buses.create_index(
            [("current_status", ASCENDING)],
            name="college_buses_current_status_idx"
        )


        # =====================================================
        # BUS LOG INDEXES
        # =====================================================

        bus_logs.create_index(
            [
                ("date", ASCENDING),
                ("_id", DESCENDING)
            ],
            name="bus_logs_date_id_idx"
        )

        bus_logs.create_index(
            [("bus_no", ASCENDING)],
            name="bus_logs_bus_no_idx"
        )

        bus_logs.create_index(
            [("plate", ASCENDING)],
            name="bus_logs_plate_idx"
        )


        # =====================================================
        # STAFF VEHICLE INDEXES
        # =====================================================

        staff_vehicles.create_index(
            [("plate", ASCENDING)],
            name="staff_plate_idx"
        )

        staff_vehicles.create_index(
            [("status", ASCENDING)],
            name="staff_status_idx"
        )


        # =====================================================
        # UNKNOWN VEHICLE INDEX
        # =====================================================

        unknown_vehicles.create_index(
            [("_id", DESCENDING)],
            name="unknown_id_idx"
        )


        # =====================================================
        # ALERT INDEX
        # =====================================================

        alerts.create_index(
            [
                ("read", ASCENDING),
                ("_id", DESCENDING)
            ],
            name="alerts_read_id_idx"
        )


        # =====================================================
        # DETECTION INDEX
        # =====================================================

        detections.create_index(
            [("_id", DESCENDING)],
            name="detections_id_idx"
        )


        # =====================================================
        # SUCCESS MESSAGE
        # =====================================================

        print(
            "MongoDB indexes checked/created successfully."
        )


    except Exception as e:

        print(
            "MongoDB index setup warning:",
            e
        )

# =========================================================
# REALTIME CHANGE STREAM
# =========================================================

def emit_collection_change(
    collection_name,
    operation,
    document
):

    payload = {

        "collection":
            collection_name,

        "operation":
            operation,

        "data":
            serialize_document(
                document
            ),

        "timestamp":
            datetime.now().isoformat()

    }

    try:

        socketio.emit(
            "vehicle_update",
            payload
        )

        print(
            "SocketIO event:",
            collection_name,
            operation
        )

    except Exception as e:

        print(
            "SocketIO emit error:",
            e
        )


def watch_collection(
    collection,
    collection_name
):

    while True:

        try:

            print(
                f"Starting MongoDB change stream: "
                f"{collection_name}"
            )

            pipeline = [
                {
                    "$match": {
                        "operationType": {
                            "$in": [
                                "insert",
                                "update",
                                "replace",
                                "delete"
                            ]
                        }
                    }
                }
            ]

            with collection.watch(
                pipeline,
                full_document="updateLookup"
            ) as stream:

                for change in stream:

                    operation = change.get(
                        "operationType",
                        "unknown"
                    )

                    full_document = change.get(
                        "fullDocument"
                    )

                    if operation == "delete":

                        document_key = change.get(
                            "documentKey",
                            {}
                        )

                        document = {
                            "_id":
                                document_key.get(
                                    "_id"
                                )
                        }

                    else:

                        document = (
                            full_document
                            or
                            {}
                        )

                    emit_collection_change(
                        collection_name,
                        operation,
                        document
                    )

        except Exception as e:

            print(
                f"Change stream error "
                f"({collection_name}):",
                e
            )

            time.sleep(2)


def start_change_streams():

    global CHANGE_STREAM_STARTED

    if CHANGE_STREAM_STARTED:
        return

    CHANGE_STREAM_STARTED = True

    collections = [

    (
        college_buses,
        "college_buses"
    ),

    (
        bus_logs,
        "bus_logs"
    ),

    (
        staff_vehicles,
        "staff_vehicles"
    ),

    (
        staff_logs,
        "staff_logs"
    ),

    (
        visitor_vehicles,
        "visitor_vehicles"
    ),

    (
        visitor_logs,
        "visitor_logs"
    ),

    (
        unknown_vehicles,
        "unknown_vehicles"
    ),

    (
        alerts,
        "alerts"
    )

    ]   

    for collection, name in collections:

        thread = threading.Thread(

            target=watch_collection,

            args=(
                collection,
                name
            ),

            daemon=True,

            name=f"MongoWatch-{name}"

        )

        thread.start()


# =========================================================
# VEHICLE IDENTIFICATION
# =========================================================

def identify_vehicle(plate):

    plate = clean_plate(
        plate
    )

    if not plate:

        return {

            "vehicle_type":
                "UNKNOWN",

            "verification_status":
                "UNKNOWN",

            "plate":
                ""

        }

    bus = college_buses.find_one({

        "plate":
            plate,

        "status":
            "ACTIVE"

    })

    if bus:

        return {

            "vehicle_type":
                "BUS",

            "verification_status":
                "VERIFIED",

            "bus_id":
                bus.get(
                    "bus_id"
                ),

            "bus_number":
                bus.get(
                    "bus_no"
                ),

            "plate":
                bus.get(
                    "plate"
                ),

            "driver":
                bus.get(
                    "driver"
                ),

            "route":
                bus.get(
                    "route"
                ),

            "status":
                bus.get(
                    "status"
                )

        }

    staff = staff_vehicles.find_one({

        "plate":
            plate,

        "status":
            "ACTIVE"

    })

    if staff:

        return {

            "vehicle_type":
                "STAFF",

            "verification_status":
                "VERIFIED",

            "plate":
                staff.get(
                    "plate"
                ),

            "staff_name":
                staff.get(
                    "staff_name"
                ),

            "institution":
                staff.get(
                    "institution"
                ),

            "vehicle_type_detail":
                staff.get(
                    "vehicle_type"
                ),

            "status":
                staff.get(
                    "status"
                )

        }

    return {

        "vehicle_type":
            "UNKNOWN",

        "verification_status":
            "UNKNOWN",

        "plate":
            plate

    }


# =========================================================
# DASHBOARD
# =========================================================

@app.route(
    "/api/dashboard",
    methods=["GET"]
)
def dashboard():

    try:

        total_buses = college_buses.count_documents({
            "status":
                "ACTIVE"
        })

        total_logs = bus_logs.count_documents({})

        today = datetime.now().strftime(
            "%d-%m-%Y"
        )

        today_logs = list(
            bus_logs.find({
                "date":
                    today
            })
        )
        print("DASHBOARD TODAY LOGS =", today_logs)
        entry_count = 0
        exit_count = 0

        for log in today_logs:

            direction  = str(
                log.get(
                    "direction",
                    ""
                )
            ).upper()

            if direction == "ENTRY":
                entry_count += 1

            elif direction == "EXIT":
                exit_count += 1

        return jsonify({

            "totalBuses":
                total_buses,

            "totalLogs":
                total_logs,

            "todayDetections":
                len(today_logs),

            "entryBuses":
                entry_count,

            "exitBuses":
                exit_count

        })

    except Exception as e:

        print(
            "Dashboard API error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500
# =========================================================
# VEHICLE SUMMARY
# =========================================================

@app.route(
    "/api/vehicle-summary",
    methods=["GET"]
)
def vehicle_summary():

    try:

        # =====================================================
        # 1. TOTAL REGISTERED ACTIVE FLEET
        # =====================================================

        total_registered_fleet = (
            college_buses.count_documents({
                "status": "ACTIVE"
            })
        )

        # =====================================================
        # 2. TODAY
        # =====================================================

        today = datetime.now().strftime("%d-%m-%Y")

        today_logs = list(
            bus_logs.find({
                "date": today
            })
        )

        # =====================================================
        # 3. COUNT TODAY'S ENTRY EVENTS
        # =====================================================

        entered_campus_today = 0

        # =====================================================
        # 4. COUNT TODAY'S EXIT EVENTS
        # =====================================================

        exited_campus_today = 0

        for log in today_logs:

            # Support direction/status/current_status
            # so different camera log formats still work.

            movement = str(
                log.get(
                    "direction",
                    log.get(
                        "status",
                        log.get(
                            "current_status",
                            ""
                        )
                    )
                )
            ).strip().upper()

            if movement == "ENTRY":
                entered_count += 1

            elif movement == "EXIT":
                exited_count += 1

        # =====================================================
        # RETURN
        # =====================================================

        return jsonify({

            "totalRegisteredFleet":
                total_registered_fleet,

            "enteredCampusToday":
                entered_campus_today,

            "exitedCampusToday":
                exited_campus_today

        })

    except Exception as e:

        print(
            "Vehicle summary error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500
# =========================================================
# ALL BUS LOGS
# =========================================================

@app.route(
    "/api/logs",
    methods=["GET"]
)
def all_logs():

    try:

        logs = (
            bus_logs.find()
            .sort(
                "_id",
                DESCENDING
            )
        )

        data = [
            serialize_document(log)
            for log in logs
        ]

        return jsonify(data)

    except Exception as e:

        print(
            "All logs error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# REGISTER COLLEGE BUS
# =========================================================

@app.route(
    "/api/buses/register",
    methods=["POST"]
)
def register_bus():

    print()
    print("=" * 60)
    print("REGISTER BUS REQUEST")
    print("=" * 60)

    try:

        data = request.get_json(
            silent=True
        )

        print(
            "Received JSON:",
            data
        )

        if not data:

            return jsonify({

                "success":
                    False,

                "error":
                    "No JSON data received."

            }), 400

        bus_no = str(
            data.get(
                "bus_no",
                ""
            )
        ).strip()

        plate = clean_plate(
            data.get(
                "plate",
                ""
            )
        )

        route = str(
            data.get(
                "route",
                ""
            )
        ).strip()

        driver = str(
            data.get(
                "driver",
                ""
            )
        ).strip()

        driver_phone = str(
            data.get(
                "driver_phone",
                ""
            )
        ).strip()

        seating_capacity = data.get(
            "seating_capacity",
            55
        )

        current_status = str(
            data.get(
                "current_status",
                data.get(
                    "status",
                    "INSIDE CAMPUS"
                )
            )
        ).strip().upper()

        if (
            not bus_no
            or not plate
            or not route
            or not driver
        ):

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "Bus number, plate number, "
                        "route and driver name are required."
                    )

            }), 400

        try:

            seating_capacity = int(
                seating_capacity
            )

        except (
            TypeError,
            ValueError
        ):

            return jsonify({

                "success":
                    False,

                "error":
                    "Seating capacity must be a valid number."

            }), 400

        if (
            seating_capacity < 1
            or seating_capacity > 200
        ):

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "Seating capacity must be "
                        "between 1 and 200."
                    )

            }), 400

        if current_status not in [
            "INSIDE CAMPUS",
            "OUTSIDE / TRANSIT"
        ]:

            current_status = (
                "INSIDE CAMPUS"
            )

        existing_bus_no = (
            college_buses.find_one({
                "bus_no":
                    bus_no
            })
        )

        if existing_bus_no:

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "This bus number is "
                        "already registered."
                    )

            }), 409

        existing_plate = (
            college_buses.find_one({
                "plate":
                    plate
            })
        )

        if existing_plate:

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "This plate number is "
                        "already registered."
                    )

            }), 409

        bus_id = (
            "BUS-"
            +
            datetime.now().strftime(
                "%Y%m%d%H%M%S%f"
            )
        )

        now = datetime.now()

        bus_document = {

            "bus_id":
                bus_id,

            "bus_no":
                bus_no,

            "plate":
                plate,

            "route":
                route,

            "driver":
                driver,

            "driver_phone":
                driver_phone,

            "seating_capacity":
                seating_capacity,

            "status":
                "ACTIVE",

            "current_status":
                current_status,

            "entry_time":
                None,

            "exit_time":
                None,

            "image":
                "",

            "created_at":
                now,

            "updated_at":
                now

        }

        result = (
            college_buses.insert_one(
                bus_document
            )
        )

        if not result.acknowledged:

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "MongoDB did not acknowledge "
                        "the insert."
                    )

            }), 500

        saved_bus = (
            college_buses.find_one({
                "_id":
                    result.inserted_id
            })
        )

        if not saved_bus:

            return jsonify({

                "success":
                    False,

                "error":
                    "Vehicle insert verification failed."

            }), 500

        emit_collection_change(
            "college_buses",
            "insert",
            saved_bus
        )

        return jsonify({

            "success":
                True,

            "message":
                "Bus registered successfully.",

            "bus":
                serialize_document(
                    saved_bus
                )

        }), 201

    except Exception as e:

        print(
            "REGISTER BUS ERROR:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# COLLEGE BUSES
# =========================================================

@app.route(
    "/api/buses",
    methods=["GET"]
)
def get_buses():

    try:

        buses = (
            college_buses.find()
            .sort(
                "bus_no",
                ASCENDING
            )
        )

        data = [
            serialize_document(bus)
            for bus in buses
        ]

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# ACTIVE COLLEGE BUSES
# =========================================================

@app.route(
    "/api/buses/active",
    methods=["GET"]
)
def get_active_buses():

    try:

        buses = (
            college_buses.find({
                "status":
                    "ACTIVE"
            })
            .sort(
                "bus_no",
                ASCENDING
            )
        )

        data = [
            serialize_document(bus)
            for bus in buses
        ]

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# REGISTER STAFF VEHICLE
# =========================================================

@app.route(
    "/api/staff/register",
    methods=["POST"]
)
def register_staff_vehicle():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        staff_name = str(
            data.get(
                "staff_name",
                ""
            )
        ).strip()

        plate = clean_plate(
            data.get(
                "plate",
                ""
            )
        )

        vehicle_type = str(
            data.get(
                "vehicle_type",
                ""
            )
        ).strip().upper()

        institution = str(
            data.get(
                "institution",
                ""
            )
        ).strip().upper()

        status = str(
            data.get(
                "status",
                "ACTIVE"
            )
        ).strip().upper()

        if (
            not staff_name
            or not plate
            or not vehicle_type
            or not institution
        ):

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "Staff name, plate number "
                        "vehicle type, and institution are required."
                    )

            }), 400

        if institution not in [
            "KRCT",
            "KRCE"
        ]:

            return jsonify({

                "success":
                    False,

                "error":
                    "Institution must be KRCT or KRCE."

            }), 400

        if status not in [
            "ACTIVE",
            "INACTIVE"
        ]:

            status = "ACTIVE"

        existing_plate = (
            staff_vehicles.find_one({
                "plate":
                    plate
            })
        )

        if existing_plate:

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "This plate number is "
                        "already registered as "
                        "a staff vehicle."
                    )

            }), 409

        now = datetime.now()

        staff_vehicle_document = {

            "staff_name":
                staff_name,

            "plate":
                plate,

            "vehicle_type":
                vehicle_type,

            "institution":
                institution,

            "status":
                status,

            "entry_time":
                None,

            "exit_time":
                None,

            "image":
                "",

            "created_at":
                now,

            "updated_at":
                now

        }

        result = (
            staff_vehicles.insert_one(
                staff_vehicle_document
            )
        )

        if not result.acknowledged:

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "MongoDB did not acknowledge "
                        "the insert."
                    )

            }), 500

        saved_vehicle = (
            staff_vehicles.find_one({
                "_id":
                    result.inserted_id
            })
        )

        if not saved_vehicle:

            return jsonify({

                "success":
                    False,

                "error":
                    "Staff vehicle insert verification failed."

            }), 500

        emit_collection_change(
            "staff_vehicles",
            "insert",
            saved_vehicle
        )

        return jsonify({

            "success":
                True,

            "message":
                "Staff vehicle registered successfully.",

            "vehicle":
                serialize_document(
                    saved_vehicle
                )

        }), 201

    except Exception as e:

        print(
            "Register staff vehicle error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# STAFF VEHICLES
# =========================================================

@app.route(
    "/api/staff",
    methods=["GET"]
)
def get_staff():

    try:

        vehicles = (
            staff_vehicles.find()
            .sort(
                "_id",
                DESCENDING
            )
        )

        data = [
            serialize_document(vehicle)
            for vehicle in vehicles
        ]

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# VISITOR REGISTRATION
# =========================================================

@app.route(
    "/api/visitors/register",
    methods=["POST"]
)
def register_visitor():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        vehicle_number = str(
            data.get(
                "vehicle_number",
                ""
            )
        ).strip().upper()

        visitor_name = str(
            data.get(
                "visitor_name",
                ""
            )
        ).strip()

        phone = str(
            data.get(
                "phone",
                ""
            )
        ).strip()

        purpose = str(
            data.get(
                "purpose",
                ""
            )
        ).strip()

        person_to_visit = str(
            data.get(
                "person_to_visit",
                ""
            )
        ).strip()

        department = str(
            data.get(
                "department",
                ""
            )
        ).strip()

        number_of_visitors = safe_int(
            data.get(
                "number_of_visitors",
                1
            ),
            1
        )

        visit_date = str(
            data.get(
                "visit_date",
                ""
            )
        ).strip()

        entry_time = str(
            data.get(
                "entry_time",
                ""
            )
        ).strip()

        expected_exit_time = str(
            data.get(
                "expected_exit_time",
                ""
            )
        ).strip()

        remarks = str(
            data.get(
                "remarks",
                ""
            )
        ).strip()

        status = str(
            data.get(
                "status",
                "Inside"
            )
        ).strip()

        if not vehicle_number:

            return jsonify({

                "success":
                    False,

                "message":
                    "Vehicle number is required"

            }), 400

        if not visitor_name:

            return jsonify({

                "success":
                    False,

                "message":
                    "Visitor name is required"

            }), 400

        if not phone:

            return jsonify({

                "success":
                    False,

                "message":
                    "Phone number is required"

            }), 400

        if not purpose:

            return jsonify({

                "success":
                    False,

                "message":
                    "Purpose of visit is required"

            }), 400

        if not person_to_visit:

            return jsonify({

                "success":
                    False,

                "message":
                    "Person to visit is required"

            }), 400

        if number_of_visitors < 1:
            number_of_visitors = 1

        now = datetime.now()

        visitor_id = (
            "VIS-"
            + now.strftime(
                "%Y%m%d%H%M%S"
            )
            + now.strftime(
                "%f"
            )
        )

        visitor_document = {

            "visitor_id":
                visitor_id,

            "vehicle_number":
                vehicle_number,

            "plate":
                vehicle_number,

            "visitor_name":
                visitor_name,

            "name":
                visitor_name,

            "phone":
                phone,

            "purpose":
                purpose,

            "person_to_visit":
                person_to_visit,

            "department":
                department,

            "number_of_visitors":
                number_of_visitors,

            "visit_date":
                visit_date,

            "entry_time":
                entry_time,

            "expected_exit_time":
                expected_exit_time,

            "remarks":
                remarks,

            "status":
                status,

            "entry_datetime":
                now,

            "exit_datetime":
                None,

            "created_at":
                now,

            "updated_at":
                now

        }

        vehicle_result = (
            unknown_vehicles.insert_one(
                visitor_document
            )
        )

        visitor_log = {

            "visitor_id":
                visitor_id,

            "vehicle_number":
                vehicle_number,

            "plate":
                vehicle_number,

            "visitor_name":
                visitor_name,

            "phone":
                phone,

            "purpose":
                purpose,

            "person_to_visit":
                person_to_visit,

            "department":
                department,

            "number_of_visitors":
                number_of_visitors,

            "visit_date":
                visit_date,

            "entry_time":
                entry_time,

            "expected_exit_time":
                expected_exit_time,

            "remarks":
                remarks,

            "status":
                status,

            "action":
                "ENTRY",

            "entry_datetime":
                now,

            "created_at":
                now

        }

        log_result = (
            visitor_logs.insert_one(
                visitor_log
            )
        )

        saved_visitor = (
            unknown_vehicles.find_one({

                "_id":
                    vehicle_result.inserted_id

            })
        )

        if saved_visitor:

            saved_visitor["_id"] = str(
                saved_visitor["_id"]
            )

            for key in [
                "created_at",
                "updated_at",
                "entry_datetime",
                "exit_datetime"
            ]:

                if isinstance(
                    saved_visitor.get(key),
                    datetime
                ):

                    saved_visitor[key] = (
                        saved_visitor[key].isoformat()
                    )

        try:

            socketio.emit(
                "visitor_registered",
                {
                    "visitor":
                        saved_visitor
                }
            )

        except Exception as socket_error:

            print(
                "Visitor socket notification error:",
                socket_error
            )

        return jsonify({

            "success":
                True,

            "message":
                "Visitor registered successfully",

            "visitor":
                saved_visitor,

            "visitor_id":
                visitor_id,

            "vehicle_inserted_id":
                str(
                    vehicle_result.inserted_id
                ),

            "log_inserted_id":
                str(
                    log_result.inserted_id
                )

        }), 201

    except Exception as e:

        print(
            "Visitor registration error:",
            e
        )

        return jsonify({

            "success":
                False,

            "message":
                "Failed to register visitor",

            "error":
                str(e)

        }), 500


# =========================================================
# GET ALL VISITORS
# =========================================================

@app.route(
    "/api/visitors",
    methods=["GET"]
)
def get_visitors():

    try:

        visitors = list(
            visitor_vehicles.find()
            .sort(
                "created_at",
                DESCENDING
            )
        )

        for visitor in visitors:

            visitor["_id"] = str(
                visitor["_id"]
            )

            for key in [
                "created_at",
                "updated_at",
                "entry_datetime",
                "exit_datetime"
            ]:

                if isinstance(
                    visitor.get(key),
                    datetime
                ):

                    visitor[key] = (
                        visitor[key].isoformat()
                    )

        return jsonify({

            "success":
                True,

            "visitors":
                visitors,

            "count":
                len(visitors)

        }), 200

    except Exception as e:

        return jsonify({

            "success":
                False,

            "message":
                "Failed to fetch visitors",

            "visitors":
                [],

            "error":
                str(e)

        }), 500


# =========================================================
# ALERTS
# =========================================================

@app.route(
    "/api/alerts",
    methods=["GET"]
)
def get_alerts():

    try:

        alert_data = (
            alerts.find()
            .sort(
                "_id",
                DESCENDING
            )
        )

        data = [
            serialize_document(alert)
            for alert in alert_data
        ]

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route(
    "/api/notifications",
    methods=["GET"]
)
def get_notifications():

    try:

        notifications = (
            alerts.find({
                "read":
                    False
            })
            .sort(
                "_id",
                DESCENDING
            )
            .limit(10)
        )

        data = []

        for notification in notifications:

            item = serialize_document(
                notification
            )

            if item:
                item.pop(
                    "read",
                    None
                )

            data.append(item)

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# CLEAR NOTIFICATIONS
# =========================================================

@app.route(
    "/api/notifications/clear",
    methods=["POST"]
)
def clear_notifications():

    try:

        result = alerts.update_many(

            {
                "read":
                    False
            },

            {
                "$set": {
                    "read":
                        True
                }
            }

        )

        socketio.emit(
            "notifications_cleared",
            {
                "cleared":
                    result.modified_count
            }
        )

        return jsonify({

            "success":
                True,

            "cleared":
                result.modified_count

        })

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# RAW DETECTIONS
# =========================================================

@app.route(
    "/api/detections",
    methods=["GET"]
)
def get_detections():

    try:

        detection_data = (
            detections.find()
            .sort(
                "_id",
                DESCENDING
            )
        )

        data = [
            serialize_document(item)
            for item in detection_data
        ]

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# IDENTIFY VEHICLE
# =========================================================

@app.route(
    "/api/identify/<plate>",
    methods=["GET"]
)
def identify_vehicle_api(plate):

    return jsonify(
        identify_vehicle(
            plate
        )
    )


# =========================================================
# SINGLE BUS
# =========================================================

@app.route(
    "/api/bus/<bus_no>",
    methods=["GET"]
)
def get_single_bus(bus_no):

    try:

        bus = college_buses.find_one({

            "bus_no":
                str(bus_no)

        })

        if not bus:

            return jsonify({

                "error":
                    "Bus not found"

            }), 404

        return jsonify(
            serialize_document(
                bus
            )
        )

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# SINGLE VEHICLE
# =========================================================

@app.route(
    "/api/vehicle/<plate>",
    methods=["GET"]
)
def get_vehicle(plate):

    try:

        clean = clean_plate(
            plate
        )

        bus = college_buses.find_one({
            "plate":
                clean
        })

        if bus:

            return jsonify({

                "type":
                    "BUS",

                "data":
                    serialize_document(
                        bus
                    )

            })

        staff = staff_vehicles.find_one({
            "plate":
                clean
        })

        if staff:

            return jsonify({

                "type":
                    "STAFF",

                "data":
                    serialize_document(
                        staff
                    )

            })

        return jsonify({

            "type":
                "UNKNOWN",

            "plate":
                clean

        })

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# EXCEL REPORT
# =========================================================

def create_excel(
    rows,
    filename,
    report_title="IN/OUT X Vehicle Report"
):

    workbook = Workbook()

    worksheet = workbook.active

    worksheet.title = "Vehicle Report"

    # -----------------------------------------------------
    # TITLE
    # -----------------------------------------------------

    worksheet.merge_cells(
        "A1:K1"
    )

    title_cell = worksheet["A1"]

    title_cell.value = report_title

    title_cell.font = Font(
        bold=True,
        size=16
    )

    title_cell.alignment = Alignment(
        horizontal="center",
        vertical="center"
    )

    # -----------------------------------------------------
    # GENERATED TIME
    # -----------------------------------------------------

    worksheet.merge_cells(
        "A2:K2"
    )

    worksheet["A2"] = (
        "Generated: "
        +
        datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S"
        )
    )

    worksheet["A2"].alignment = Alignment(
        horizontal="center"
    )

    # -----------------------------------------------------
    # HEADERS
    # -----------------------------------------------------

    headers = [

        "Bus ID",
        "Bus No",
        "Plate",
        "Driver",
        "Route",
        "Status",
        "Date",
        "Time",
        "OCR Plate",
        "OCR Bus Number",
        "Image"

    ]

    header_row = 4

    for column_index, header in enumerate(
        headers,
        start=1
    ):

        cell = worksheet.cell(
            row=header_row,
            column=column_index
        )

        cell.value = header

        cell.font = Font(
            bold=True
        )

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )

        cell.fill = PatternFill(
            fill_type="solid",
            fgColor="1F2937"
        )

    # -----------------------------------------------------
    # DATA
    # -----------------------------------------------------

    for row_index, row in enumerate(
        rows,
        start=header_row + 1
    ):

        values = [

            row.get(
                "bus_id",
                ""
            ),

            row.get(
                "bus_no",
                row.get(
                    "bus_number",
                    ""
                )
            ),

            row.get(
                "plate",
                ""
            ),

            row.get(
                "driver",
                ""
            ),

            row.get(
                "route",
                ""
            ),

            row.get(
                "status",
                ""
            ),

            row.get(
                "date",
                ""
            ),

            row.get(
                "time",
                ""
            ),

            row.get(
                "ocr_plate",
                ""
            ),

            row.get(
                "ocr_bus_number",
                ""
            ),

            row.get(
                "image",
                row.get(
                    "image_path",
                    ""
                )
            )

        ]

        for column_index, value in enumerate(
            values,
            start=1
        ):

            cell = worksheet.cell(
                row=row_index,
                column=column_index
            )

            cell.value = str(
                value
            )

            cell.alignment = Alignment(
                vertical="center"
            )

    # -----------------------------------------------------
    # COLUMN WIDTHS
    # -----------------------------------------------------

    widths = [

        24,
        12,
        18,
        25,
        25,
        15,
        15,
        15,
        20,
        22,
        50

    ]

    for index, width in enumerate(
        widths,
        start=1
    ):

        worksheet.column_dimensions[
            get_column_letter(index)
        ].width = width

    # -----------------------------------------------------
    # BORDER
    # -----------------------------------------------------

    thin = Side(
        style="thin",
        color="D1D5DB"
    )

    for row_cells in worksheet.iter_rows(
        min_row=header_row,
        max_row=worksheet.max_row,
        min_col=1,
        max_col=len(headers)
    ):

        for cell in row_cells:

            cell.border = Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

    worksheet.freeze_panes = "A5"

    output = BytesIO()

    workbook.save(
        output
    )

    output.seek(0)

    return send_file(

        output,

        download_name=filename,

        as_attachment=True,

        mimetype=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        )

    )


# =========================================================
# PDF REPORT
# =========================================================

def create_pdf(
    rows,
    filename,
    report_title
):

    output = BytesIO()

    # =====================================================
    # A4 PORTRAIT
    # =====================================================

    document = SimpleDocTemplate(

        output,

        pagesize=A4,

        rightMargin=10 * mm,

        leftMargin=10 * mm,

        topMargin=8 * mm,

        bottomMargin=15 * mm

    )

    styles = getSampleStyleSheet()

    # =====================================================
    # STYLES
    # =====================================================

    title_style = ParagraphStyle(

        "INOUTXTitle",

        parent=styles["Title"],

        fontName="Helvetica-Bold",

        fontSize=15,

        leading=18,

        alignment=TA_CENTER,

        textColor=colors.HexColor(
            "#123B68"
        ),

        spaceAfter=2 * mm

    )

    normal_style = ParagraphStyle(

        "INOUTXNormal",

        parent=styles["Normal"],

        fontName="Helvetica",

        fontSize=7,

        leading=8.5,

        alignment=TA_LEFT,

        textColor=colors.HexColor(
            "#1F2937"
        )

    )

    center_style = ParagraphStyle(

        "INOUTXCenter",

        parent=normal_style,

        alignment=TA_CENTER

    )

    small_style = ParagraphStyle(

        "INOUTXSmall",

        parent=normal_style,

        fontSize=6.5,

        leading=8

    )

    section_style = ParagraphStyle(

        "INOUTXSection",

        parent=styles["Heading2"],

        fontName="Helvetica-Bold",

        fontSize=10,

        leading=12,

        textColor=colors.HexColor(
            "#123B68"
        ),

        spaceBefore=2 * mm,

        spaceAfter=2 * mm

    )

    header_style = ParagraphStyle(

        "INOUTXTableHeader",

        parent=normal_style,

        fontName="Helvetica-Bold",

        fontSize=6.5,

        leading=7.5,

        alignment=TA_CENTER,

        textColor=colors.white

    )

    summary_label_style = ParagraphStyle(

        "SummaryLabel",

        parent=normal_style,

        fontName="Helvetica-Bold",

        fontSize=7,

        leading=8,

        alignment=TA_CENTER,

        textColor=colors.HexColor(
            "#374151"
        )

    )

    summary_value_style = ParagraphStyle(

        "SummaryValue",

        parent=normal_style,

        fontName="Helvetica-Bold",

        fontSize=12,

        leading=14,

        alignment=TA_CENTER,

        textColor=colors.HexColor(
            "#123B68"
        )

    )

    story = []

    # =====================================================
    # HEADER WITH BOTH COLLEGE LOGOS
    # =====================================================

    story.append(
        build_pdf_header(
            report_title,
            len(rows)
        )
    )

    story.append(
        Spacer(
            1,
            4 * mm
        )
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    entry_count = 0
    exit_count = 0

    for row in rows:

        status = str(
            row.get(
                "status",
                ""
            )
        ).strip().upper()

        if status == "ENTRY":

            entry_count += 1

        elif status == "EXIT":

            exit_count += 1

    summary_table = Table(

        [[

            Paragraph(
                "TOTAL RECORDS",
                summary_label_style
            ),

            Paragraph(
                "ENTRY",
                summary_label_style
            ),

            Paragraph(
                "EXIT",
                summary_label_style
            )

        ], [

            Paragraph(
                str(len(rows)),
                summary_value_style
            ),

            Paragraph(
                str(entry_count),
                summary_value_style
            ),

            Paragraph(
                str(exit_count),
                summary_value_style
            )

        ]],

        colWidths=[
            60 * mm,
            60 * mm,
            60 * mm
        ]

    )

    summary_table.setStyle(

        TableStyle([

            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor(
                    "#F3F4F6"
                )
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor(
                    "#D1D5DB"
                )
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                2.5 * mm
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                2.5 * mm
            )

        ])

    )

    story.append(
        summary_table
    )

    story.append(
        Spacer(
            1,
            4 * mm
        )
    )

    # =====================================================
    # REPORT TABLE
    # =====================================================

    story.append(
        Paragraph(
            "Vehicle Detection Records",
            section_style
        )
    )

    table_data = [[

        Paragraph(
            "Bus No",
            header_style
        ),

        Paragraph(
            "Plate",
            header_style
        ),

        Paragraph(
            "Driver",
            header_style
        ),

        Paragraph(
            "Route",
            header_style
        ),

        Paragraph(
            "Status",
            header_style
        ),

        Paragraph(
            "Date",
            header_style
        ),

        Paragraph(
            "Time",
            header_style
        ),

        Paragraph(
            "OCR Plate",
            header_style
        ),

        Paragraph(
            "OCR Bus No",
            header_style
        ),

        Paragraph(
            "Captured Image",
            header_style
        )

    ]]

    # =====================================================
    # TABLE ROWS
    # =====================================================

    for row in rows:

        image_value = row.get(
            "image",
            row.get(
                "image_path",
                ""
            )
        )

        image_cell = Paragraph(
            "No image",
            small_style
        )

        full_image_path = (
            resolve_captured_image(
                image_value
            )
        )

        if full_image_path:

            image_object = create_captured_image(
                full_image_path,
                38,
                26
            )

            if image_object:

                image_cell = image_object

        bus_no = str(
            row.get(
                "bus_no",
                row.get(
                    "bus_number",
                    "-"
                )
            )
            or "-"
        )

        plate = str(
            row.get(
                "plate",
                "-"
            )
            or "-"
        )

        driver = str(
            row.get(
                "driver",
                "-"
            )
            or "-"
        )

        route = str(
            row.get(
                "route",
                "-"
            )
            or "-"
        )

        status = str(
            row.get(
                "status",
                "-"
            )
            or "-"
        )

        date = str(
            row.get(
                "date",
                "-"
            )
            or "-"
        )

        log_time = str(
            row.get(
                "time",
                "-"
            )
            or "-"
        )

        ocr_plate = str(
            row.get(
                "ocr_plate",
                "-"
            )
            or "-"
        )

        ocr_bus_number = str(
            row.get(
                "ocr_bus_number",
                "-"
            )
            or "-"
        )

        table_data.append([

            Paragraph(
                bus_no,
                small_style
            ),

            Paragraph(
                plate,
                small_style
            ),

            Paragraph(
                driver,
                small_style
            ),

            Paragraph(
                route,
                small_style
            ),

            Paragraph(
                status,
                small_style
            ),

            Paragraph(
                date,
                small_style
            ),

            Paragraph(
                log_time,
                small_style
            ),

            Paragraph(
                ocr_plate,
                small_style
            ),

            Paragraph(
                ocr_bus_number,
                small_style
            ),

            image_cell

        ])

    # =====================================================
    # EMPTY REPORT
    # =====================================================

    if len(table_data) == 1:

        table_data.append([

            Paragraph(
                "No vehicle records found.",
                small_style
            ),

            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            ""

        ])

    # =====================================================
    # A4 PORTRAIT TABLE WIDTH
    # =====================================================

    table = Table(

        table_data,

        repeatRows=1,

        colWidths=[

            15 * mm,   # Bus No
            23 * mm,   # Plate
            25 * mm,   # Driver
            26 * mm,   # Route
            18 * mm,   # Status
            20 * mm,   # Date
            17 * mm,   # Time
            23 * mm,   # OCR Plate
            23 * mm,   # OCR Bus
            30 * mm    # Image

        ],

        hAlign="CENTER"

    )

    # =====================================================
    # TABLE STYLE
    # =====================================================

    table.setStyle(

        TableStyle([

            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor(
                    "#123B68"
                )
            ),

            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.4,
                colors.HexColor(
                    "#9CA3AF"
                )
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),

            (
                "ALIGN",
                (0, 0),
                (-1, -1),
                "CENTER"
            ),

            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor(
                        "#F8FAFC"
                    )
                ]
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                2
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                2
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                2
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                2
            )

        ])

    )

    story.append(
        table
    )

    # =====================================================
    # BUILD PDF
    # =====================================================

    document.build(

        story,

        onFirstPage=pdf_footer,

        onLaterPages=pdf_footer

    )

    output.seek(0)

    return send_file(

        output,

        download_name=filename,

        as_attachment=True,

        mimetype="application/pdf"

    )


# =========================================================
# DOWNLOAD EXCEL - TODAY
# =========================================================

@app.route(
    "/api/download/today",
    methods=["GET"]
)
def download_today():

    try:

        start, end = get_report_period(
            "today"
        )

        rows = fetch_report_rows(
            start,
            end
        )

        return create_excel(

            rows,

            "Today_Report.xlsx",

            "IN/OUT X - Today's Vehicle Report"

        )

    except Exception as e:

        print(
            "Today Excel error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# DOWNLOAD EXCEL - WEEKLY
# =========================================================

@app.route(
    "/api/download/weekly",
    methods=["GET"]
)
def download_weekly():

    try:

        start, end = get_report_period(
            "weekly"
        )

        rows = fetch_report_rows(
            start,
            end
        )

        return create_excel(

            rows,

            "Weekly_Report.xlsx",

            "IN/OUT X - Weekly Vehicle Report"

        )

    except Exception as e:

        print(
            "Weekly Excel error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# DOWNLOAD EXCEL - MONTHLY
# =========================================================

@app.route(
    "/api/download/monthly",
    methods=["GET"]
)
def download_monthly():

    try:

        start, end = get_report_period(
            "monthly"
        )

        rows = fetch_report_rows(
            start,
            end
        )

        return create_excel(

            rows,

            "Monthly_Report.xlsx",

            "IN/OUT X - Monthly Vehicle Report"

        )

    except Exception as e:

        print(
            "Monthly Excel error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# PDF - UNIFIED ENDPOINT
# =========================================================

@app.route(
    "/api/download/pdf",
    methods=["GET"]
)
def download_pdf():

    try:

        period = request.args.get(
            "period",
            "today"
        ).strip().lower()

        if period not in [
            "today",
            "weekly",
            "monthly"
        ]:

            return jsonify({

                "success":
                    False,

                "error":
                    (
                        "Invalid period. "
                        "Use today, weekly or monthly."
                    )

            }), 400

        start, end = get_report_period(
            period
        )

        rows = fetch_report_rows(
            start,
            end
        )

        if period == "today":

            filename = (
                "Today_Report.pdf"
            )

            title = (
                "Today's Vehicle Report"
            )

        elif period == "weekly":

            filename = (
                "Weekly_Report.pdf"
            )

            title = (
                "Weekly Vehicle Report"
            )

        else:

            filename = (
                "Monthly_Report.pdf"
            )

            title = (
                "Monthly Vehicle Report"
            )

        print(
            f"PDF report requested: "
            f"{period} | records={len(rows)}"
        )

        return create_pdf(

            rows,

            filename,

            title

        )

    except Exception as e:

        print(
            "Unified PDF error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# PDF - TODAY
# =========================================================

@app.route(
    "/api/download/pdf/today",
    methods=["GET"]
)
def download_pdf_today():

    try:

        start, end = get_report_period(
            "today"
        )

        rows = fetch_report_rows(
            start,
            end
        )

        return create_pdf(

            rows,

            "Today_Report.pdf",

            "Today's Vehicle Report"

        )

    except Exception as e:

        print(
            "Today PDF error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# PDF - WEEKLY
# =========================================================

@app.route(
    "/api/download/pdf/weekly",
    methods=["GET"]
)
def download_pdf_weekly():

    try:

        start, end = get_report_period(
            "weekly"
        )

        rows = fetch_report_rows(
            start,
            end
        )

        return create_pdf(

            rows,

            "Weekly_Report.pdf",

            "Weekly Vehicle Report"

        )

    except Exception as e:

        print(
            "Weekly PDF error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# PDF - MONTHLY
# =========================================================

@app.route(
    "/api/download/pdf/monthly",
    methods=["GET"]
)
def download_pdf_monthly():

    try:

        start, end = get_report_period(
            "monthly"
        )

        rows = fetch_report_rows(
            start,
            end
        )

        return create_pdf(

            rows,

            "Monthly_Report.pdf",

            "Monthly Vehicle Report"

        )

    except Exception as e:

        print(
            "Monthly PDF error:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# CAPTURED FRAMES
# =========================================================

@app.route(
    "/captured-frames/<path:filename>"
)
def captured_frames(filename):

    return send_from_directory(

        CAPTURED_FRAMES_DIR,

        filename

    )


# =========================================================
# CAPTURED IMAGES API
# =========================================================

@app.route(
    "/api/captured-images",
    methods=["GET"]
)
def captured_images():

    try:

        logs = (
            bus_logs.find({
                "image": {
                    "$exists":
                        True,

                    "$ne":
                        ""
                }
            })
            .sort(
                "_id",
                DESCENDING
            )
        )

        data = []

        for row in logs:

            image_path = row.get(
                "image",
                row.get(
                    "image_path",
                    ""
                )
            )

            if not image_path:
                continue

            filename = os.path.basename(
                str(image_path)
                .replace(
                    "\\",
                    "/"
                )
            )

            if not filename:
                continue

            image_url = (
                "/captured-frames/"
                +
                filename
            )

            data.append({

                "_id":
                    str(
                        row.get(
                            "_id",
                            ""
                        )
                    ),

                "image":
                    image_url,

                "bus_no":
                    row.get(
                        "bus_no",
                        row.get(
                            "bus_number",
                            "-"
                        )
                    ),

                "vehicle_no":
                    row.get(
                        "plate",
                        "-"
                    ),

                "route":
                    row.get(
                        "route",
                        "-"
                    ),

                "status":
                    row.get(
                        "status",
                        "-"
                    ),

                "entry_time":
                    row.get(
                        "time",
                        "-"
                    ),

                "exit_time":
                    row.get(
                        "exit_time",
                        "-"
                    )

            })

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# REALTIME MANUAL DETECTION
# =========================================================

@app.route(
    "/api/detection-update",
    methods=["POST"]
)
def detection_update():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        socketio.emit(
            "vehicle_update",
            {

                "collection":
                    data.get(
                        "collection",
                        "detections"
                    ),

                "operation":
                    data.get(
                        "operation",
                        "insert"
                    ),

                "data":
                    data.get(
                        "data",
                        data
                    ),

                "timestamp":
                    datetime.now().isoformat()

            }
        )

        return jsonify({

            "success":
                True

        })

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# ASSETS
# =========================================================

@app.route(
    "/assets/<path:filename>"
)
def assets(filename):

    return send_from_directory(
        ASSETS_DIR,
        filename
    )


@app.route(
    "/react-assets/<path:filename>"
)
def react_assets(filename):

    return send_from_directory(

        os.path.join(
            DIST_DIR,
            "react-assets"
        ),

        filename

    )
# =========================================================
# SERVE ORIGINAL HTML FILES FOR REACT LOADER
# =========================================================

@app.route("/html/<path:filename>")

def serve_html_file(filename):

    file_path = os.path.join(
        HTML_DIR,
        filename
    )

    if not os.path.isfile(file_path):
        return jsonify({
            "error": "HTML file not found"
        }), 404

    return send_from_directory(
        HTML_DIR,
        filename
    )


# =========================================================
# HTML / REACT
# =========================================================

@app.route(
    "/<path:filename>"
)
def html_files(filename):

    if filename.startswith(
        "api/"
    ):

        return jsonify({
            "error":
                "API endpoint not found"
        }), 404

    # -----------------------------------------------------
    # Static HTML pages
    # -----------------------------------------------------

    static_html_pages = {
        "login.html",
    "register.html",
    "forgot-password.html",
    "reset-password.html",
    "download.html",
    "camera.html",
    "profile.html",
    "system-config.html",
    "404.html",
    "500.html"
    }
    print(
    "HTML DEBUG:",
    filename,
    "HTML_DIR:",
    HTML_DIR,
    "FILE:",
    os.path.join(
        HTML_DIR,
        filename
    ),
    "EXISTS:",
    os.path.isfile(
        os.path.join(
            HTML_DIR,
            filename
        )
    )
)

    if (
        filename in static_html_pages
        and
        os.path.isfile(
            os.path.join(
                HTML_DIR,
                filename
            )
        )
    ):

        return send_from_directory(
            HTML_DIR,
            filename
        )

    # -----------------------------------------------------
    # React pages
    # -----------------------------------------------------

    react_pages = {
    "index.html",
    "staff-vehicles.html",
    "unknown-vehicles.html",
    "vehicle.html"
}

    if (
        filename in react_pages
        and
        os.path.isfile(
            REACT_INDEX_FILE
        )
    ):

        return send_file(
            REACT_INDEX_FILE
        )

    # ⬇️ INGA IRUNDHU UN EXISTING REMAINING CODE CONTINUE AAGANUM

    # -----------------------------------------------------
    # Security check
    # -----------------------------------------------------

    file_path = os.path.abspath(

        os.path.join(
            HTML_DIR,
            filename
        )

    )

    html_root = os.path.abspath(
        HTML_DIR
    )

    if not file_path.startswith(
        html_root + os.sep
    ):

        return jsonify({

            "error":
                "Page not found"

        }), 404

    # -----------------------------------------------------
    # Normal HTML file
    # -----------------------------------------------------

    if os.path.isfile(
        file_path
    ):

        return send_from_directory(
            HTML_DIR,
            filename
        )

    return jsonify({

        "error":
            "Page not found"

    }), 404


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route(
    "/api/health",
    methods=["GET"]
)
def health():

    try:

        result = db.command(
            "ping"
        )

        return jsonify({

            "status":
                "OK",

            "database":
                db.name,

            "mongodb":
                "Atlas",

            "ping":
                result

        })

    except Exception as e:

        return jsonify({

            "status":
                "ERROR",

            "message":
                str(e)

        }), 500


# =========================================================
# TEST DATABASE INSERT
# =========================================================

@app.route(
    "/api/test-db",
    methods=["POST"]
)
def test_database():

    try:

        test_document = {

            "test":
                True,

            "message":
                "IN_OUT_X MongoDB test",

            "created_at":
                datetime.now()

        }

        result = db[
            "test_connection"
        ].insert_one(
            test_document
        )

        saved = db[
            "test_connection"
        ].find_one({

            "_id":
                result.inserted_id

        })

        return jsonify({

            "success":
                True,

            "message":
                "MongoDB insert test successful.",

            "database":
                db.name,

            "collection":
                "test_connection",

            "document":
                serialize_document(
                    saved
                )

        })

    except Exception as e:

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500


# =========================================================
# SOCKET.IO
# =========================================================

@socketio.on(
    "connect"
)
def socket_connect():

    print(
        "Dashboard Socket.IO client connected."
    )

    try:

        socketio.emit(
            "connection_status",
            {

                "connected":
                    True,

                "timestamp":
                    datetime.now().isoformat()

            }
        )

    except Exception as e:

        print(
            "Connection event error:",
            e
        )


@socketio.on(
    "disconnect"
)
def socket_disconnect():

    print(
        "Dashboard Socket.IO client disconnected."
    )


# =========================================================
# HOME
# =========================================================
# =========================================================
# HOME
# =========================================================

@app.route(
    "/",
    methods=["GET"],
    endpoint="home_page"
)
def home():

    return send_from_directory(
        HTML_DIR,
        "login.html"
    )
# =========================================================
# STARTUP
# =========================================================

def startup():

    print()
    print("=" * 60)
    print("IN/OUT X FRONTEND")
    print("=" * 60)

    print(
        "Database      : MongoDB Atlas"
    )

    print(
        "Database Name : IN_OUTX"
    )

    print(
        "Frontend      : "
        + HTML_DIR
    )

    print(
        "Captured      : "
        + CAPTURED_FRAMES_DIR
    )

    print(
        "KRCE Logo     : "
        + KRCE_LOGO
    )

    print(
        "KRCT Logo     : "
        + KRCT_LOGO
    )

    print(
        "Server        : "
        "http://127.0.0.1:5000"
    )

    print(
        "Realtime      : "
        "MongoDB Change Streams + Socket.IO"
    )

    print("=" * 60)
    print()

    # -----------------------------------------------------
    # Create captured frames directory
    # -----------------------------------------------------

    if not os.path.isdir(
        CAPTURED_FRAMES_DIR
    ):

        print(
            "WARNING: captured_frames directory "
            "does not exist."
        )

        try:

            os.makedirs(
                CAPTURED_FRAMES_DIR,
                exist_ok=True
            )

            print(
                "Created captured_frames directory."
            )

        except Exception as e:

            print(
                "Could not create captured_frames:",
                e
            )

    # -----------------------------------------------------
    # Check logos
    # -----------------------------------------------------

    print(
        "KRCE logo exists:",
        os.path.isfile(
            KRCE_LOGO
        )
    )

    print(
        "KRCT logo exists:",
        os.path.isfile(
            KRCT_LOGO
        )
    )

    if not os.path.isfile(
        KRCE_LOGO
    ):

        print(
            "WARNING: KRCE logo not found."
        )

        print(
            "Expected:"
        )

        print(
            KRCE_LOGO
        )

    if not os.path.isfile(
        KRCT_LOGO
    ):

        print(
            "WARNING: KRCT logo not found."
        )

        print(
            "Expected:"
        )

        print(
            KRCT_LOGO
        )

    # -----------------------------------------------------
    # MongoDB
    # -----------------------------------------------------

    if not check_mongodb():

        print(
            "WARNING: MongoDB connection failed."
        )

        print(
            "The server will still start, "
            "but database operations will fail."
        )

    # -----------------------------------------------------
    # Indexes
    # -----------------------------------------------------

    ensure_indexes()

    # -----------------------------------------------------
    # Change streams
    # -----------------------------------------------------

    try:

        start_change_streams()

    except Exception as e:

        print(
            "Change stream startup warning:",
            e
        )

print("MAIL_SERVER:", os.getenv("MAIL_SERVER"))
print("MAIL_PORT:", os.getenv("MAIL_PORT"))
print("MAIL_USERNAME:", os.getenv("MAIL_USERNAME"))
print("MAIL_FROM:", os.getenv("MAIL_FROM"))
print("MAIL_PASSWORD configured:", bool(os.getenv("MAIL_PASSWORD")))





#---------------
# =========================================================
# TODAY BUS ENTRIES
# =========================================================

@app.route("/api/today_entries", methods=["GET"])
def today_entries():
    try:
        # Supports both:
        #   /api/today_entries?date=today
        #   /api/today_entries?date=yesterday
        # and an explicit DD-MM-YYYY date.
        requested_date = request.args.get("date", "today").strip().lower()

        today_date = datetime.now().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        if requested_date == "yesterday":
            target_date = today_date - timedelta(days=1)
            target_date_string = target_date.strftime("%d-%m-%Y")

        elif requested_date in ("today", ""):
            target_date_string = today_date.strftime("%d-%m-%Y")

        else:
            # Allow the frontend to request an exact date if needed.
            try:
                target_date_string = datetime.strptime(
                    requested_date,
                    "%d-%m-%Y"
                ).strftime("%d-%m-%Y")
            except ValueError:
                return jsonify({
                    "success": False,
                    "error": "Invalid date. Use today, yesterday, or DD-MM-YYYY."
                }), 400

        logs = (
            bus_logs.find({"date": target_date_string})
            .sort("_id", DESCENDING)
        )

        data = []

        for row in logs:
            data.append({
                "_id": str(row.get("_id", "")),
                "bus_id": row.get("bus_id", ""),
                "bus_no": row.get(
                    "bus_no",
                    row.get("bus_number", "")
                ),
                "vehicle_no": row.get("plate", ""),
                "plate": row.get("plate", ""),
                "driver": row.get("driver", ""),
                "route": row.get("route", ""),
                "status": row.get("status", "ENTRY"),
                "date": row.get("date", ""),
                "time": row.get("time", ""),
                "exit_time": row.get("exit_time", ""),
                "image": row.get(
                    "image",
                    row.get("image_path", "")
                ),
                "ocr_plate": row.get("ocr_plate", ""),
                "ocr_bus_number": row.get(
                    "ocr_bus_number",
                    ""
                )
            })

        return jsonify(data)

    except Exception as e:
        print("Today entries error:", e)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    startup()

    socketio.run(

        app,

        host="0.0.0.0",

        port=5000,

        debug=True,

        use_reloader=False

    )

# ============================================================
# IN/OUT X - CONFIGURATION
# ============================================================

# ============================================================
# PROJECT INFORMATION
# ============================================================

PROJECT_NAME = "IN/OUT X"
VERSION = "1.0"


# ============================================================
# CAMERA CONFIGURATION
# ============================================================

CAMERA_SOURCE =0
CAMERA_ID = "Gate_01"
GATE_NAME = "Main Gate"


# ============================================================
# AI / VEHICLE DETECTION
# ============================================================

YOLO_MODEL = "models/yolov8n.pt"

DETECTION_CONFIDENCE = 0.50

TRACKER_CONFIG = "bytetrack.yaml"


# ============================================================
# VIRTUAL LINE CONFIGURATION
# ============================================================
#
# IMPORTANT:
# Coordinates are intentionally left as None for now.
#
# Format:
#
# ENTRY_LINE = (
#     (x1, y1),
#     (x2, y2)
# )
#
# EXIT_LINE = (
#     (x1, y1),
#     (x2, y2)
# )
#
# We will fill the real coordinates after checking
# the actual camera frame.
# ============================================================

ENTRY_LINE = ((46, 179), (588, 180))
EXIT_LINE = ((48, 343), (586, 339))


# ============================================================
# LINE CROSSING
# ============================================================

# Ignore very tiny point movements caused by tracker jitter.
LINE_CROSSING_MIN_MOVEMENT = 5


# Once a vehicle crosses its first line, its movement
# (ENTRY / EXIT) becomes locked.
FIRST_LINE_LOCK = True


# ============================================================
# OCR CONFIGURATION
# ============================================================

OCR_CONFIDENCE = 0.80

# OCR will be allowed only AFTER first virtual-line crossing.
OCR_AFTER_FIRST_LINE_ONLY = True

# Maximum time OCR / identity pipeline can run
# after first line crossing.
IDENTITY_WINDOW_SECONDS = 4.0

# Process OCR approximately once during this interval.
OCR_INTERVAL = 1.0

# Maximum number of OCR attempts for one tracked vehicle.
MAX_OCR_FRAMES = 10

# Number of repeated stable results required.
REQUIRED_STABLE_RESULTS = 2


# ============================================================
# PLATE DETECTION
# ============================================================

PLATE_CONFIDENCE = 0.20
PLATE_IOU = 0.45
PLATE_IMAGE_SIZE = 640
MAX_PLATE_DETECTIONS = 5


# ============================================================
# IDENTITY MATCHING
# ============================================================

# RapidFuzz minimum similarity score.
PLATE_FUZZY_THRESHOLD = 80

# Bus-number fuzzy matching can be enabled later
# when the exact DB matching flow is implemented.
BUS_NUMBER_FUZZY_THRESHOLD = 80


# ============================================================
# TRACKING
# ============================================================

# How long a missing track can remain in memory.
TRACK_MISSING_TIMEOUT = 0.5

# Initial warmup frames.
WARMUP_FRAMES = 2


# ============================================================
# DUPLICATE PROTECTION
# ============================================================

DUPLICATE_COOLDOWN = 20


# ============================================================
# CAMERA RETRY
# ============================================================

CAMERA_RETRY_COUNT = 3
CAMERA_RETRY_DELAY = 1.0


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

# NOTE:
# Current mongodb.py loads Atlas credentials from .env.
# This value is kept for backward compatibility.
MONGO_URI = ""

DATABASE_NAME = "IN_OUTX"


# ============================================================
# COLLECTION NAMES
# ============================================================

COLLEGE_BUS_COLLECTION = "college_buses"
BUS_LOG_COLLECTION = "bus_logs"
STAFF_VEHICLE_COLLECTION = "staff_vehicles"
STAFF_LOG_COLLECTION = "staff_logs"
UNKNOWN_VEHICLE_COLLECTION = "visitor_vehicles"

VEHICLE_STATE_COLLECTION = "vehicle_states"
GATE_EVENT_COLLECTION = "gate_events"


# ============================================================
# IMAGE STORAGE
# ============================================================

CAPTURE_FOLDER = "images/captured"


# ============================================================
# REPORT STORAGE
# ============================================================

REPORT_FOLDER = "reports"


# ============================================================
# ALARM
# ============================================================

ALARM_SOUND = "alarm.wav"
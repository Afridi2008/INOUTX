import cv2
import time
from collections import Counter
import asyncio
import threading
import websockets
from datetime import datetime

from config import (
    CAMERA_SOURCE,
    ENTRY_LINE,
    EXIT_LINE,
    FIRST_LINE_LOCK,
    LINE_CROSSING_MIN_MOVEMENT,
    OCR_AFTER_FIRST_LINE_ONLY,
)

from tracker import track_bus
from frame_capture import save_frame
from plate_detector import detect_plate
from ocr import read_plate, read_bus_number
from metadata import create_metadata
from notification import create_notification

from mongodb import (
    insert_bus_log,
    find_college_bus,
    find_best_matching_bus,
    find_staff_vehicle,
    save_staff_vehicle,
    save_unknown_vehicle,
)


# ============================================================
# LINE CONFIGURATION
# ============================================================
#
# IMPORTANT:
#
# FIRST / TOP LINE     = EXIT
# SECOND / BOTTOM LINE = ENTRY
#
# IMPORTANT BEHAVIOUR:
#
# The vehicle bounding box itself is checked against the line.
# The moment ANY PART of the vehicle touches a line,
# that line becomes the FIRST LINE.
#
# EXIT  -> OCR -> validation -> EXIT log
# ENTRY -> OCR -> validation -> ENTRY log
#
# The second line is NOT required.
#
# ============================================================


# ============================================================
# TEMPORARY LINE COORDINATE SELECTOR
# ============================================================

line_selection_points = []
line_selection_done = False


def line_mouse_callback(event, x, y, flags, param):

    global line_selection_points
    global line_selection_done

    if line_selection_done:
        return

    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if len(line_selection_points) >= 4:
        return

    line_selection_points.append((x, y))

    point_number = len(line_selection_points)

    print()
    print(
        f"LINE SELECTOR CLICK {point_number}: "
        f"({x}, {y})"
    )

    # --------------------------------------------------------
    # FIRST / TOP = EXIT
    # --------------------------------------------------------

    if point_number == 1:

        print(
            "EXIT start point selected."
        )

    elif point_number == 2:

        print(
            "EXIT line selected."
        )

    # --------------------------------------------------------
    # SECOND / BOTTOM = ENTRY
    # --------------------------------------------------------

    elif point_number == 3:

        print(
            "ENTRY start point selected."
        )

    elif point_number == 4:

        print(
            "ENTRY line selected."
        )

        exit_start = line_selection_points[0]
        exit_end = line_selection_points[1]

        entry_start = line_selection_points[2]
        entry_end = line_selection_points[3]

        print()
        print("=" * 60)
        print("LINE COORDINATES READY")
        print("=" * 60)

        print()
        print("Paste this into config.py:")
        print()

        print(
            f"EXIT_LINE = "
            f"({exit_start}, {exit_end})"
        )

        print(
            f"ENTRY_LINE = "
            f"({entry_start}, {entry_end})"
        )

        print()
        print("=" * 60)
        print("LINE ORDER:")
        print("FIRST / TOP     = EXIT")
        print("SECOND / BOTTOM = ENTRY")
        print("=" * 60)

        print()
        print("Press R to reset line selection.")
        print("Press Q to quit.")
        print("=" * 60)

        line_selection_done = True


def draw_line_selector(frame):

    if not line_selection_points:
        return

    # --------------------------------------------------------
    # DRAW CLICK POINTS
    # --------------------------------------------------------

    for index, point in enumerate(
        line_selection_points
    ):

        cv2.circle(
            frame,
            point,
            7,
            (255, 0, 255),
            -1
        )

        cv2.putText(
            frame,
            str(index + 1),
            (
                point[0] + 10,
                point[1] - 10
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 0, 255),
            2
        )

    # ========================================================
    # FIRST / TOP LINE = EXIT
    # ========================================================

    if len(line_selection_points) >= 2:

        cv2.line(
            frame,
            line_selection_points[0],
            line_selection_points[1],
            (0, 165, 255),
            3
        )

        cv2.putText(
            frame,
            "EXIT - LINE 1",
            (
                line_selection_points[0][0] + 10,
                max(
                    25,
                    line_selection_points[0][1] - 15
                )
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (0, 165, 255),
            2
        )

    # ========================================================
    # SECOND / BOTTOM LINE = ENTRY
    # ========================================================

    if len(line_selection_points) >= 4:

        cv2.line(
            frame,
            line_selection_points[2],
            line_selection_points[3],
            (0, 255, 255),
            3
        )

        cv2.putText(
            frame,
            "ENTRY - LINE 2",
            (
                line_selection_points[2][0] + 10,
                max(
                    25,
                    line_selection_points[2][1] - 15
                )
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (0, 255, 255),
            2
        )

    # ========================================================
    # INSTRUCTIONS
    # ========================================================

    if not line_selection_done:

        if len(line_selection_points) == 0:

            instruction = "CLICK EXIT START"

        elif len(line_selection_points) == 1:

            instruction = "CLICK EXIT END"

        elif len(line_selection_points) == 2:

            instruction = "CLICK ENTRY START"

        else:

            instruction = "CLICK ENTRY END"

        cv2.putText(
            frame,
            instruction,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 255),
            2
        )

    else:

        cv2.putText(
            frame,
            "LINE 1 EXIT | LINE 2 ENTRY | FIRST TOUCH WINS",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (255, 255, 255),
            2
        )


# ============================================================
# SETTINGS
# ============================================================

WARMUP_FRAMES = 2

MAX_OCR_FRAMES = 10

OCR_INTERVAL = 1

REQUIRED_STABLE_RESULTS = 2

DUPLICATE_COOLDOWN = 20

CAMERA_RETRY_COUNT = 3

CAMERA_RETRY_DELAY = 1.0

MIN_PLATE_CONFIDENCE = 0.20

TRACK_MISSING_TIMEOUT = 0.5


# ============================================================
# VEHICLE CLASS NAMES
# ============================================================

VEHICLE_NAMES = {
    2: "CAR",
    3: "MOTORCYCLE",
    5: "BUS",
    7: "TRUCK",
}


# ============================================================
# LINE HELPERS
# ============================================================

def _orientation(a, b, c):

    value = (
        (b[1] - a[1]) * (c[0] - b[0])
        -
        (b[0] - a[0]) * (c[1] - b[1])
    )

    if abs(value) < 1e-9:
        return 0

    return 1 if value > 0 else 2


def _on_segment(a, b, c):

    return (
        min(a[0], c[0]) <= b[0] <= max(a[0], c[0])
        and
        min(a[1], c[1]) <= b[1] <= max(a[1], c[1])
    )


def segments_intersect(
    p1,
    q1,
    p2,
    q2
):

    o1 = _orientation(
        p1,
        q1,
        p2
    )

    o2 = _orientation(
        p1,
        q1,
        q2
    )

    o3 = _orientation(
        p2,
        q2,
        p1
    )

    o4 = _orientation(
        p2,
        q2,
        q1
    )

    if o1 != o2 and o3 != o4:
        return True

    if o1 == 0 and _on_segment(
        p1,
        p2,
        q1
    ):
        return True

    if o2 == 0 and _on_segment(
        p1,
        q2,
        q1
    ):
        return True

    if o3 == 0 and _on_segment(
        p2,
        p1,
        q2
    ):
        return True

    if o4 == 0 and _on_segment(
        p2,
        q1,
        q2
    ):
        return True

    return False


def _line_to_points(line):

    if line is None:
        return None

    try:

        start, end = line

        return (
            (
                int(start[0]),
                int(start[1])
            ),
            (
                int(end[0]),
                int(end[1])
            )
        )

    except Exception:

        return None


# ============================================================
# NEW: BOUNDING BOX / LINE TOUCH DETECTION
# ============================================================
#
# IMPORTANT:
#
# Old logic:
#
#     bottom-center -> line
#
# That causes delayed detection.
#
# New logic:
#
#     FULL VEHICLE BOUNDING BOX -> line
#
# If ANY EDGE/CORNER of the vehicle touches the virtual line,
# it is considered a line touch.
#
# This makes detection start when the BUS BODY first touches
# the line, instead of waiting until the bottom-center crosses.
#
# ============================================================

def line_touches_box(
    box,
    line
):

    if box is None:
        return False

    points = _line_to_points(line)

    if points is None:
        return False

    try:

        x1, y1, x2, y2 = map(
            int,
            box
        )

    except Exception:

        return False

    if x2 < x1:
        x1, x2 = x2, x1

    if y2 < y1:
        y1, y2 = y2, y1

    line_start, line_end = points

    # --------------------------------------------------------
    # BOX CORNERS
    # --------------------------------------------------------

    top_left = (
        x1,
        y1
    )

    top_right = (
        x2,
        y1
    )

    bottom_right = (
        x2,
        y2
    )

    bottom_left = (
        x1,
        y2
    )

    # --------------------------------------------------------
    # BOX EDGES
    # --------------------------------------------------------

    box_edges = [

        (
            top_left,
            top_right
        ),

        (
            top_right,
            bottom_right
        ),

        (
            bottom_right,
            bottom_left
        ),

        (
            bottom_left,
            top_left
        )
    ]

    # --------------------------------------------------------
    # LINE TOUCHES ANY BOX EDGE
    # --------------------------------------------------------

    for edge_start, edge_end in box_edges:

        if segments_intersect(
            edge_start,
            edge_end,
            line_start,
            line_end
        ):

            return True

    # --------------------------------------------------------
    # EXTRA CHECK:
    #
    # If the virtual line endpoint happens to be inside
    # the bounding box.
    # --------------------------------------------------------

    for px, py in (
        line_start,
        line_end
    ):

        if (
            x1 <= px <= x2
            and
            y1 <= py <= y2
        ):

            return True

    return False


def box_center(box):

    if box is None:
        return None

    try:

        x1, y1, x2, y2 = map(
            int,
            box
        )

        return (
            int((x1 + x2) / 2),
            int((y1 + y2) / 2)
        )

    except Exception:

        return None


def distance_between_points(
    point_a,
    point_b
):

    if point_a is None or point_b is None:
        return float("inf")

    dx = (
        point_a[0]
        -
        point_b[0]
    )

    dy = (
        point_a[1]
        -
        point_b[1]
    )

    return (
        dx * dx
        +
        dy * dy
    )


# ============================================================
# FIRST LINE TOUCH
# ============================================================
#
# FIRST / TOP     = EXIT
# SECOND / BOTTOM = ENTRY
#
# IMPORTANT:
#
# The first line physically touched by the VEHICLE BODY wins.
#
# Once stored:
#
#     first_crossed_line
#
# NEVER changes.
#
# ============================================================

def check_first_touched_line(
    previous_box,
    current_box
):

    if current_box is None:
        return None

    # --------------------------------------------------------
    # Current box touches which lines?
    # --------------------------------------------------------

    touched_lines = []

    exit_line = _line_to_points(
        EXIT_LINE
    )

    entry_line = _line_to_points(
        ENTRY_LINE
    )

    if exit_line is not None:

        if line_touches_box(
            current_box,
            exit_line
        ):

            touched_lines.append(
                "EXIT"
            )

    if entry_line is not None:

        if line_touches_box(
            current_box,
            entry_line
        ):

            touched_lines.append(
                "ENTRY"
            )

    # --------------------------------------------------------
    # No line touched
    # --------------------------------------------------------

    if not touched_lines:

        return None

    # --------------------------------------------------------
    # Only one line touched
    # --------------------------------------------------------

    if len(touched_lines) == 1:

        return touched_lines[0]

    # ========================================================
    # BOTH LINES TOUCHED IN SAME FRAME
    # ========================================================
    #
    # This can happen if:
    #
    # 1. Bus is physically large.
    # 2. Tracker jumps several pixels/frames.
    #
    # In that case choose the line closest to the previous
    # vehicle position.
    #
    # ========================================================

    if previous_box is None:

        # Safe deterministic fallback:
        # TOP is EXIT, BOTTOM is ENTRY.
        return "EXIT"

    previous_center = box_center(
        previous_box
    )

    if previous_center is None:

        return "EXIT"

    exit_center = (
        (
            exit_line[0][0]
            +
            exit_line[1][0]
        ) // 2,
        (
            exit_line[0][1]
            +
            exit_line[1][1]
        ) // 2
    ) if exit_line is not None else None

    entry_center = (
        (
            entry_line[0][0]
            +
            entry_line[1][0]
        ) // 2,
        (
            entry_line[0][1]
            +
            entry_line[1][1]
        ) // 2
    ) if entry_line is not None else None

    exit_distance = distance_between_points(
        previous_center,
        exit_center
    )

    entry_distance = distance_between_points(
        previous_center,
        entry_center
    )

    if exit_distance <= entry_distance:

        return "EXIT"

    return "ENTRY"


# ============================================================
# OLD FUNCTION NAME COMPATIBILITY
# ============================================================
#
# Keep this function so any other part of the project that
# imports check_first_crossed_line does not immediately break.
#
# The actual camera loop now uses check_first_touched_line().
#
# ============================================================

def check_first_crossed_line(
    previous_center,
    current_center
):

    if previous_center is None:
        return None

    if current_center is None:
        return None

    dx = (
        current_center[0]
        -
        previous_center[0]
    )

    dy = (
        current_center[1]
        -
        previous_center[1]
    )

    movement_distance_sq = (
        dx * dx
        +
        dy * dy
    )

    if movement_distance_sq < (
        LINE_CROSSING_MIN_MOVEMENT ** 2
    ):

        return None

    lines = (
        (
            "EXIT",
            _line_to_points(
                EXIT_LINE
            )
        ),
        (
            "ENTRY",
            _line_to_points(
                ENTRY_LINE
            )
        ),
    )

    for line_name, points in lines:

        if points is None:
            continue

        line_start, line_end = points

        if segments_intersect(
            previous_center,
            current_center,
            line_start,
            line_end
        ):

            return line_name

    return None


def draw_virtual_lines(frame):

    # ========================================================
    # FIRST / TOP = EXIT
    # ========================================================

    exit_points = _line_to_points(
        EXIT_LINE
    )

    if exit_points is not None:

        start, end = exit_points

        cv2.line(
            frame,
            start,
            end,
            (0, 165, 255),
            3
        )

        label_x = min(
            start[0],
            end[0]
        ) + 10

        label_y = max(
            25,
            min(
                start[1],
                end[1]
            ) - 10
        )

        cv2.putText(
            frame,
            "LINE 1 - EXIT",
            (
                label_x,
                label_y
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 165, 255),
            2
        )

    # ========================================================
    # SECOND / BOTTOM = ENTRY
    # ========================================================

    entry_points = _line_to_points(
        ENTRY_LINE
    )

    if entry_points is not None:

        start, end = entry_points

        cv2.line(
            frame,
            start,
            end,
            (0, 255, 255),
            3
        )

        label_x = min(
            start[0],
            end[0]
        ) + 10

        label_y = max(
            25,
            min(
                start[1],
                end[1]
            ) - 10
        )

        cv2.putText(
            frame,
            "LINE 2 - ENTRY",
            (
                label_x,
                label_y
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2
        )


# ============================================================
# CAMERA
# ============================================================

def open_camera(source):

    print("=" * 60)
    print("Opening camera...")
    print("Configured source:", source)

    camera_source = source

    if isinstance(source, str):

        source = source.strip()

        if source.isdigit():

            camera_source = int(
                source
            )

    for attempt in range(
        1,
        CAMERA_RETRY_COUNT + 1
    ):

        print(
            f"Camera open attempt "
            f"{attempt}/{CAMERA_RETRY_COUNT}"
        )

        camera = cv2.VideoCapture(
            camera_source
        )

        try:

            camera.set(
                cv2.CAP_PROP_BUFFERSIZE,
                1
            )

        except Exception:
            pass

        if camera.isOpened():

            print(
                "Camera opened successfully."
            )

            time.sleep(0.5)

            return camera

        camera.release()

        print(
            "Camera could not be opened."
        )

        if attempt < CAMERA_RETRY_COUNT:

            print(
                f"Retrying in "
                f"{CAMERA_RETRY_DELAY} second..."
            )

            time.sleep(
                CAMERA_RETRY_DELAY
            )

    return None


# ============================================================
# SAFE CROP
# ============================================================

def get_safe_crop(
    frame,
    box
):

    height, width = frame.shape[:2]

    try:

        x1, y1, x2, y2 = map(
            int,
            box.xyxy[0].tolist()
        )

    except Exception:

        return None, (
            0,
            0,
            0,
            0
        )

    x1 = max(
        0,
        min(
            x1,
            width - 1
        )
    )

    y1 = max(
        0,
        min(
            y1,
            height - 1
        )
    )

    x2 = max(
        0,
        min(
            x2,
            width
        )
    )

    y2 = max(
        0,
        min(
            y2,
            height
        )
    )

    if x2 <= x1 or y2 <= y1:

        return None, (
            x1,
            y1,
            x2,
            y2
        )

    crop = frame[
        y1:y2,
        x1:x2
    ]

    if crop.size == 0:

        return None, (
            x1,
            y1,
            x2,
            y2
        )

    return crop, (
        x1,
        y1,
        x2,
        y2
    )


# ============================================================
# PLATE CROP
# ============================================================

def get_best_plate_crop(
    vehicle_crop,
    plate_results
):

    if (
        vehicle_crop is None
        or
        not plate_results
    ):

        return (
            None,
            None,
            0.0
        )

    try:

        vehicle_height, vehicle_width = (
            vehicle_crop.shape[:2]
        )

    except Exception:

        return (
            None,
            None,
            0.0
        )

    best_box = None
    best_area = 0
    best_confidence = 0.0

    for detection in plate_results:

        if not isinstance(
            detection,
            dict
        ):
            continue

        try:

            confidence = float(
                detection.get(
                    "confidence",
                    0.0
                )
            )

            if confidence < MIN_PLATE_CONFIDENCE:
                continue

            raw_box = detection.get(
                "box"
            )

            if (
                not raw_box
                or
                len(raw_box) != 4
            ):
                continue

            px1, py1, px2, py2 = map(
                int,
                raw_box
            )

            px1 = max(
                0,
                min(
                    px1,
                    vehicle_width - 1
                )
            )

            py1 = max(
                0,
                min(
                    py1,
                    vehicle_height - 1
                )
            )

            px2 = max(
                0,
                min(
                    px2,
                    vehicle_width
                )
            )

            py2 = max(
                0,
                min(
                    py2,
                    vehicle_height
                )
            )

            if (
                px2 <= px1
                or
                py2 <= py1
            ):
                continue

            area = (
                px2 - px1
            ) * (
                py2 - py1
            )

            if area > best_area:

                best_area = area

                best_box = (
                    px1,
                    py1,
                    px2,
                    py2
                )

                best_confidence = confidence

        except Exception as e:

            print(
                "Plate box parsing warning:",
                e
            )

    if best_box is None:

        return (
            None,
            None,
            0.0
        )

    px1, py1, px2, py2 = best_box

    plate_width = (
        px2 - px1
    )

    plate_height = (
        py2 - py1
    )

    pad_x = max(
        2,
        int(
            plate_width * 0.08
        )
    )

    pad_y = max(
        2,
        int(
            plate_height * 0.15
        )
    )

    crop_x1 = max(
        0,
        px1 - pad_x
    )

    crop_y1 = max(
        0,
        py1 - pad_y
    )

    crop_x2 = min(
        vehicle_width,
        px2 + pad_x
    )

    crop_y2 = min(
        vehicle_height,
        py2 + pad_y
    )

    plate_crop = vehicle_crop[
        crop_y1:crop_y2,
        crop_x1:crop_x2
    ]

    if plate_crop.size == 0:

        return (
            None,
            best_box,
            best_confidence
        )

    return (
        plate_crop,
        best_box,
        best_confidence
    )


# ============================================================
# OCR HELPERS
# ============================================================

def clean_result(value):

    if value is None:
        return ""

    return str(
        value
    ).strip().upper()


def get_most_common(values):

    if not values:
        return ""

    cleaned = []

    for value in values:

        value = clean_result(
            value
        )

        if value:

            cleaned.append(
                value
            )

    if not cleaned:
        return ""

    counts = Counter(
        cleaned
    )

    return counts.most_common(
        1
    )[0][0]


def is_stable(values):

    if not values:
        return False

    cleaned = []

    for value in values:

        value = clean_result(
            value
        )

        if value:

            cleaned.append(
                value
            )

    if not cleaned:
        return False

    counts = Counter(
        cleaned
    )

    _, count = (
        counts.most_common(
            1
        )[0]
    )

    return (
        count
        >=
        REQUIRED_STABLE_RESULTS
    )


def normalize_bus_number(value):

    if not value:
        return ""

    value = str(
        value
    ).strip().upper()

    value = "".join(
        char
        for char in value
        if char.isalnum()
    )

    return value


# ============================================================
# IMAGE
# ============================================================

def save_detection_image(
    frame,
    track_id
):

    try:

        return save_frame(
            frame,
            track_id
        )

    except Exception as e:

        print(
            "Frame save error:",
            e
        )

        return ""


# ============================================================
# METADATA
# ============================================================

def create_basic_metadata(
    track_id,
    plate,
    image_path,
    vehicle_type
):

    try:

        metadata = create_metadata(
            bus_id=track_id,
            plate=plate,
            image_path=image_path
        )

    except Exception:

        now = datetime.now()

        metadata = {

            "bus_id": track_id,

            "plate": plate,

            "image": image_path,

            "date": now.strftime(
                "%Y-%m-%d"
            ),

            "time": now.strftime(
                "%H:%M:%S"
            )
        }

    metadata[
        "vehicle_type"
    ] = vehicle_type

    metadata[
        "detected_at"
    ] = datetime.now()

    return metadata


# ============================================================
# DUPLICATES
# ============================================================

def is_duplicate(
    plate,
    recent_plates,
    current_time
):

    plate = clean_result(
        plate
    )

    if not plate:
        return False

    last_seen = recent_plates.get(
        plate
    )

    if last_seen is None:
        return False

    return (
        current_time
        -
        last_seen
    ) < DUPLICATE_COOLDOWN


def remember_plate(
    plate,
    recent_plates,
    current_time
):

    plate = clean_result(
        plate
    )

    if plate:

        recent_plates[
            plate
        ] = current_time


# ============================================================
# COLLEGE BUS VALIDATION
# ============================================================

def validate_college_bus(
    stable_plate,
    stable_bus_number
):

    stable_plate = clean_result(
        stable_plate
    )

    stable_bus_number = (
        normalize_bus_number(
            stable_bus_number
        )
    )

    print()
    print("=" * 60)
    print("COLLEGE BUS VALIDATION")
    print("=" * 60)

    print(
        "OCR Plate       :",
        stable_plate or "NONE"
    )

    print(
        "OCR Vehicle No  :",
        stable_bus_number or "NONE"
    )

    if not stable_plate:

        print(
            "FAILED: Plate not available."
        )

        return None

    if not stable_bus_number:

        print(
            "FAILED: Vehicle number not available."
        )

        return None

    print()
    print(
        "Checking plate in MongoDB..."
    )

    try:

        bus_data = find_college_bus(
            stable_plate
        )

    except Exception as e:

        print(
            "Plate lookup error:",
            e
        )

        bus_data = None

    if bus_data is None:

        print(
            "Exact plate not found."
        )

        print(
            "Trying fuzzy plate matching..."
        )

        try:

            bus_data = (
                find_best_matching_bus(
                    stable_plate,
                    threshold=80
                )
            )

        except Exception as e:

            print(
                "Fuzzy plate lookup error:",
                e
            )

            bus_data = None

    if bus_data is None:

        print(
            "FAILED: Plate does not match."
        )

        return None

    registered_bus_number = (
        bus_data.get(
            "bus_no",
            ""
        )
    )

    registered_bus_number = (
        normalize_bus_number(
            registered_bus_number
        )
    )

    print()
    print(
        "MongoDB Plate      :",
        bus_data.get(
            "plate",
            ""
        )
    )

    print(
        "MongoDB Vehicle No :",
        registered_bus_number
    )

    if (
        registered_bus_number
        !=
        stable_bus_number
    ):

        print()
        print(
            "FAILED: Vehicle number mismatch."
        )

        print(
            "OCR      :",
            stable_bus_number
        )

        print(
            "MongoDB  :",
            registered_bus_number
        )

        print(
            "College bus validation FAILED."
        )

        return None

    print()
    print("=" * 60)
    print("BOTH IDENTITIES MATCHED")
    print("=" * 60)

    print(
        "Plate       :",
        stable_plate
    )

    print(
        "Vehicle No  :",
        stable_bus_number
    )

    print(
        "Bus No      :",
        bus_data.get(
            "bus_no",
            ""
        )
    )

    print(
        "Route       :",
        bus_data.get(
            "route",
            ""
        )
    )

    print("=" * 60)

    return bus_data


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_vehicle(
    vehicle_type,
    stable_plate,
    stable_bus_number
):

    print()
    print("-" * 60)
    print("CLASSIFICATION STARTED")

    print(
        "Vehicle type      :",
        vehicle_type
    )

    print(
        "Stable plate      :",
        stable_plate or "NONE"
    )

    print(
        "Stable vehicle no :",
        stable_bus_number or "NONE"
    )

    print("-" * 60)

    if vehicle_type == "BUS":

        bus_data = validate_college_bus(
            stable_plate,
            stable_bus_number
        )

        if bus_data is not None:

            return (
                "COLLEGE_BUS",
                bus_data
            )

        print(
            "BUS detected, but BOTH "
            "identities did not match."
        )

        return (
            "UNKNOWN",
            None
        )

    if stable_plate:

        print(
            "Checking staff vehicle..."
        )

        try:

            staff_data = find_staff_vehicle(
                stable_plate
            )

        except Exception as e:

            print(
                "Staff lookup error:",
                e
            )

            staff_data = None

        if staff_data is not None:

            print(
                "STAFF VEHICLE FOUND"
            )

            return (
                "STAFF",
                staff_data
            )

    print(
        "No registered vehicle match."
    )

    return (
        "UNKNOWN",
        None
    )


# ============================================================
# SAVE COLLEGE BUS
# ============================================================

def save_college_bus(
    frame,
    track_id,
    stable_plate,
    stable_bus_number,
    bus_data,
    recent_plates,
    recent_bus_numbers,
    current_time,
    movement="ENTRY",
    crossing_time=None
):

    atlas_bus_id = bus_data.get(
        "bus_id",
        ""
    )

    atlas_bus_no = bus_data.get(
        "bus_no",
        ""
    )

    atlas_plate = bus_data.get(
        "plate",
        ""
    )

    atlas_driver = bus_data.get(
        "driver",
        ""
    )

    atlas_route = bus_data.get(
        "route",
        ""
    )

    atlas_status = bus_data.get(
        "status",
        "ACTIVE"
    )

    duplicate_plate = clean_result(
        atlas_plate
    )

    duplicate_bus_no = (
        normalize_bus_number(
            atlas_bus_no
        )
    )

    if is_duplicate(
        duplicate_plate,
        recent_plates,
        current_time
    ):

        print(
            "Duplicate vehicle ignored:",
            duplicate_plate
        )

        return True

    if duplicate_bus_no:

        last_seen = (
            recent_bus_numbers.get(
                duplicate_bus_no
            )
        )

        if (
            last_seen is not None
            and
            (
                current_time
                -
                last_seen
            ) < DUPLICATE_COOLDOWN
        ):

            print(
                "Duplicate bus number ignored:",
                duplicate_bus_no
            )

            return True

    image_path = save_detection_image(
        frame,
        track_id
    )

    if crossing_time is None:

        crossing_time = datetime.now()

    metadata = create_basic_metadata(
        track_id,
        atlas_plate or stable_plate,
        image_path,
        "BUS"
    )

    metadata["bus_id"] = atlas_bus_id

    metadata["bus_no"] = atlas_bus_no

    metadata["bus_number"] = atlas_bus_no

    metadata["plate"] = (
        atlas_plate
        or
        stable_plate
    )

    metadata["driver"] = atlas_driver

    metadata["route"] = atlas_route

    metadata["registered_status"] = (
        atlas_status
    )

    metadata["movement"] = movement

    if movement == "ENTRY":

        metadata["entry_time"] = (
            crossing_time
        )

        metadata["exit_time"] = None

        metadata["status"] = "ARRIVED"

    else:

        metadata["entry_time"] = None

        metadata["exit_time"] = (
            crossing_time
        )

        metadata["status"] = "EXITED"

    metadata["ocr_plate"] = (
        clean_result(
            stable_plate
        )
    )

    metadata["ocr_bus_number"] = (
        normalize_bus_number(
            stable_bus_number
        )
    )

    metadata["classification"] = (
        "COLLEGE_BUS"
    )

    try:

        log_id = insert_bus_log(
            metadata
        )

    except Exception as e:

        print()
        print(
            "ERROR saving college bus:"
        )

        print(
            e
        )

        return False

    print()
    print("=" * 60)

    if movement == "ENTRY":

        print(
            "COLLEGE BUS ENTRY SAVED TO ATLAS"
        )

    else:

        print(
            "COLLEGE BUS EXIT SAVED TO ATLAS"
        )

    print("=" * 60)

    print(
        "MongoDB Log ID :",
        log_id
    )

    print(
        "Bus No         :",
        atlas_bus_no
    )

    print(
        "Plate          :",
        atlas_plate or stable_plate
    )

    print(
        "OCR Bus No     :",
        stable_bus_number
    )

    print(
        "Driver         :",
        atlas_driver
    )

    print(
        "Route          :",
        atlas_route
    )

    print(
        "Movement       :",
        movement
    )

    print(
        "Status         :",
        metadata["status"]
    )

    print(
        "Crossing Time  :",
        crossing_time
    )

    print(
        "Image          :",
        image_path
    )

    print("=" * 60)

    remember_plate(
        duplicate_plate,
        recent_plates,
        current_time
    )

    if duplicate_bus_no:

        recent_bus_numbers[
            duplicate_bus_no
        ] = current_time

    if movement == "ENTRY":

        create_notification(
            "Bus Detected",
            (
                f"{atlas_bus_no} "
                f"({atlas_plate}) "
                "entered KRCT Gate."
            ),
            "success"
        )

    else:

        create_notification(
            "Bus Detected",
            (
                f"{atlas_bus_no} "
                f"({atlas_plate}) "
                "exited KRCT Gate."
            ),
            "success"
        )

    return True


# ============================================================
# STAFF
# ============================================================

def save_staff_detection(
    frame,
    track_id,
    stable_plate,
    staff_data,
    recent_plates,
    current_time,
    vehicle_type,
    movement="ENTRY",
    crossing_time=None
):

    if not stable_plate:
        return False

    if is_duplicate(
        stable_plate,
        recent_plates,
        current_time
    ):

        print(
            "Duplicate staff vehicle ignored:",
            stable_plate
        )

        return True

    image_path = save_detection_image(
        frame,
        track_id
    )

    staff_name = staff_data.get(
        "staff_name",
        ""
    )

    registered_plate = (
        staff_data.get(
            "plate",
            stable_plate
        )
    )

    registered_vehicle_type = (
        staff_data.get(
            "vehicle_type",
            vehicle_type
        )
    )

    status = staff_data.get(
        "status",
        "ACTIVE"
    )

    if crossing_time is None:

        crossing_time = datetime.now()

    metadata = {

        "plate": registered_plate,

        "ocr_plate": stable_plate,

        "staff_name": staff_name,

        "vehicle_type":
            registered_vehicle_type,

        "detected_vehicle_type":
            vehicle_type,

        "status": status,

        "classification": "STAFF",

        "movement": movement,

        "image": image_path,

        "date": datetime.now().strftime(
            "%Y-%m-%d"
        ),

        "time": datetime.now().strftime(
            "%H:%M:%S"
        ),

        "detected_at": datetime.now()
    }

    if movement == "ENTRY":

        metadata["entry_time"] = (
            crossing_time
        )

        metadata["exit_time"] = None

    else:

        metadata["entry_time"] = None

        metadata["exit_time"] = (
            crossing_time
        )

    try:

        log_id = save_staff_vehicle(
            metadata
        )

        print()
        print("=" * 60)

        print(
            "STAFF VEHICLE SAVED TO ATLAS"
        )

        print("=" * 60)

        print(
            "MongoDB Log ID :",
            log_id
        )

        print(
            "Staff Name     :",
            staff_name
        )

        print(
            "Plate          :",
            registered_plate
        )

        print(
            "Movement       :",
            movement
        )

        print(
            "Image          :",
            image_path
        )

        print("=" * 60)

    except Exception as e:

        print(
            "ERROR saving staff vehicle:",
            e
        )

        return False

    remember_plate(
        stable_plate,
        recent_plates,
        current_time
    )

    return True


# ============================================================
# UNKNOWN
# ============================================================

def save_unknown_detection(
    frame,
    track_id,
    stable_plate,
    vehicle_type,
    recent_plates,
    current_time,
    movement="ENTRY",
    crossing_time=None
):

    if stable_plate:

        if is_duplicate(
            stable_plate,
            recent_plates,
            current_time
        ):

            print(
                "Duplicate unknown vehicle ignored:",
                stable_plate
            )

            return True

    image_path = save_detection_image(
        frame,
        track_id
    )

    if crossing_time is None:

        crossing_time = datetime.now()

    metadata = {

        "plate": stable_plate,

        "ocr_plate": stable_plate,

        "vehicle_type": vehicle_type,

        "classification": "UNKNOWN",

        "movement": movement,

        "image": image_path,

        "date": datetime.now().strftime(
            "%Y-%m-%d"
        ),

        "time": datetime.now().strftime(
            "%H:%M:%S"
        ),

        "detected_at": datetime.now(),

        "status": "UNKNOWN"
    }

    if movement == "ENTRY":

        metadata["entry_time"] = (
            crossing_time
        )

        metadata["exit_time"] = None

    else:

        metadata["entry_time"] = None

        metadata["exit_time"] = (
            crossing_time
        )

    try:

        log_id = save_unknown_vehicle(
            metadata
        )

        print()
        print("=" * 60)

        print(
            "UNKNOWN VEHICLE SAVED TO ATLAS"
        )

        print("=" * 60)

        print(
            "MongoDB Log ID :",
            log_id
        )

        print(
            "Vehicle Type   :",
            vehicle_type
        )

        print(
            "Plate          :",
            stable_plate
            or
            "NOT READ"
        )

        print(
            "Movement       :",
            movement
        )

        print(
            "Image          :",
            image_path
        )

        print("=" * 60)

    except Exception as e:

        print(
            "ERROR saving unknown vehicle:",
            e
        )

        return False

    if stable_plate:

        remember_plate(
            stable_plate,
            recent_plates,
            current_time
        )

    return True


# ============================================================
# LIVE CAMERA WEBSOCKET
# ============================================================

latest_frame = None

frame_lock = threading.Lock()


async def camera_websocket(websocket):

    try:

        while True:

            with frame_lock:

                frame = latest_frame

            if frame is not None:

                success, buffer = (
                    cv2.imencode(
                        ".jpg",
                        frame,
                        [
                            cv2.IMWRITE_JPEG_QUALITY,
                            80
                        ]
                    )
                )

                if success:

                    await websocket.send(
                        buffer.tobytes()
                    )

            await asyncio.sleep(
                0.07
            )

    except websockets.exceptions.ConnectionClosed:

        return

    except asyncio.CancelledError:

        return

    except Exception as e:

        print(
            "Camera WebSocket error:",
            e
        )


# ============================================================
# START CAMERA
# ============================================================

def start_camera():

    global latest_frame
    global line_selection_done

    # ========================================================
    # WEBSOCKET SERVER
    # ========================================================

    async def start_websocket_server():

        server = await websockets.serve(
            camera_websocket,
            "0.0.0.0",
            8000
        )

        print(
            "Camera WebSocket server started "
            "on ws://localhost:8000/ws/camera"
        )

        await server.wait_closed()

    def run_websocket_server():

        asyncio.run(
            start_websocket_server()
        )

    websocket_thread = threading.Thread(
        target=run_websocket_server,
        daemon=True
    )

    websocket_thread.start()

    # ========================================================
    # TRACK DATA
    # ========================================================

    vehicle_data = {}

    # ========================================================
    # DUPLICATE MEMORY
    # ========================================================

    recent_plates = {}

    recent_bus_numbers = {}

    # ========================================================
    # OPEN CAMERA
    # ========================================================

    camera = open_camera(
        CAMERA_SOURCE
    )

    if camera is None:

        print("=" * 60)

        print(
            "ERROR: Camera could not be opened."
        )

        print(
            "Check CAMERA_SOURCE in config.py."
        )

        print("=" * 60)

        return

    print("=" * 60)

    print(
        "IN/OUT X CAMERA STARTED"
    )

    print("=" * 60)

    print(
        "Source:",
        CAMERA_SOURCE
    )

    print(
        "Line 1:",
        "EXIT"
    )

    print(
        "Line 2:",
        "ENTRY"
    )

    print(
        "Detection mode:",
        "FIRST LINE TOUCH -> OCR -> DATABASE"
    )

    print(
        "BUS validation:",
        "PLATE + VEHICLE NUMBER"
    )

    print(
        "Second line:",
        "NOT REQUIRED"
    )

    print(
        "Press Q to stop."
    )

    print("=" * 60)

    # ========================================================
    # LINE SELECTOR
    # ========================================================

    cv2.namedWindow(
        "IN/OUT X - Live Camera"
    )

    cv2.setMouseCallback(
        "IN/OUT X - Live Camera",
        line_mouse_callback
    )

    # ========================================================
    # MAIN LOOP
    # ========================================================

    while True:

        ret, frame = camera.read()

        if not ret or frame is None:

            print(
                "Failed to read camera frame."
            )

            time.sleep(
                0.05
            )

            continue

        current_time = time.time()

        # ====================================================
        # YOLO TRACKING
        # ====================================================

        try:

            results = track_bus(
                frame
            )

        except Exception as e:

            print(
                "Vehicle tracking error:",
                e
            )

            results = []

        # ====================================================
        # ANNOTATED FRAME
        # ====================================================

        annotated_frame = (
            frame.copy()
        )

        try:

            if results:

                annotated_frame = (
                    results[0].plot()
                )

        except Exception:

            annotated_frame = (
                frame.copy()
            )

        # ====================================================
        # DRAW VIRTUAL LINES
        # ====================================================

        draw_virtual_lines(
            annotated_frame
        )

        draw_line_selector(
            annotated_frame
        )

        # ====================================================
        # CURRENT TRACK IDS
        # ====================================================

        current_track_ids = set()

        # ====================================================
        # PROCESS TRACKS
        # ====================================================

        for result in results:

            if result.boxes is None:
                continue

            if result.boxes.id is None:
                continue

            for box in result.boxes:

                # ==========================================
                # TRACK ID
                # ==========================================

                try:

                    track_id = int(
                        box.id[0]
                    )

                except Exception:

                    continue

                current_track_ids.add(
                    track_id
                )

                # ==========================================
                # CLASS ID
                # ==========================================

                try:

                    class_id = int(
                        box.cls[0]
                    )

                except Exception:

                    class_id = -1

                vehicle_type = (
                    VEHICLE_NAMES.get(
                        class_id,
                        "VEHICLE"
                    )
                )

                # ==========================================
                # CURRENT BOUNDING BOX
                # ==========================================

                try:

                    current_box = tuple(
                        map(
                            int,
                            box.xyxy[0].tolist()
                        )
                    )

                except Exception:

                    continue

                # ==========================================
                # CREATE TRACK STATE
                # ==========================================

                if track_id not in vehicle_data:

                    vehicle_data[
                        track_id
                    ] = {

                        "frames": 0,

                        "ocr_attempts": 0,

                        "last_ocr_frame": 0,

                        "last_seen":
                            current_time,

                        "vehicle_type":
                            vehicle_type,

                        "plates": [],

                        "bus_numbers": [],

                        # ----------------------------------
                        # BOX TRACKING
                        # ----------------------------------

                        "previous_box":
                            None,

                        "current_box":
                            current_box,

                        # ----------------------------------
                        # CENTER
                        # ----------------------------------

                        "previous_center":
                            None,

                        "current_center":
                            None,

                        # ----------------------------------
                        # FIRST LINE
                        # ----------------------------------

                        "first_crossed_line":
                            None,

                        # ----------------------------------
                        # MOVEMENT
                        # ----------------------------------

                        "movement_status":
                            None,

                        "crossing_time":
                            None,

                        # ----------------------------------
                        # OCR
                        # ----------------------------------

                        "identity_enabled":
                            False,

                        "ocr_started":
                            False,

                        "ocr_finished":
                            False,

                        # ----------------------------------
                        # DATABASE
                        # ----------------------------------

                        "database_saved":
                            False,

                        # ----------------------------------
                        # CLASSIFICATION
                        # ----------------------------------

                        "classification":
                            None,

                        "matched_data":
                            None,

                        # ----------------------------------
                        # FINAL
                        # ----------------------------------

                        "processed":
                            False,

                        "last_frame":
                            frame.copy()
                    }

                data = vehicle_data[
                    track_id
                ]

                data[
                    "last_seen"
                ] = current_time

                data[
                    "vehicle_type"
                ] = vehicle_type

                data[
                    "last_frame"
                ] = frame.copy()

                # ==========================================
                # STORE PREVIOUS / CURRENT BOX
                # ==========================================
                #
                # THIS IS THE IMPORTANT CHANGE.
                #
                # We use the FULL VEHICLE BOX to determine
                # the exact first line touched.
                #
                # ==========================================

                previous_box = data.get(
                    "current_box"
                )

                data[
                    "previous_box"
                ] = previous_box

                data[
                    "current_box"
                ] = current_box

                # ==========================================
                # CENTER ONLY FOR DISPLAY / COMPATIBILITY
                # ==========================================

                previous_center = data.get(
                    "current_center"
                )

                current_center = (
                    int(
                        (
                            current_box[0]
                            +
                            current_box[2]
                        ) / 2
                    ),
                    int(
                        (
                            current_box[1]
                            +
                            current_box[3]
                        ) / 2
                    )
                )

                data[
                    "previous_center"
                ] = previous_center

                data[
                    "current_center"
                ] = current_center

                # ==========================================
                # FIRST LINE TOUCH DETECTION
                # ==========================================
                #
                # OLD:
                #
                # bottom center crosses line
                #
                # NEW:
                #
                # vehicle bounding box touches line
                #
                # This triggers BEFORE the vehicle enters
                # the space between the two lines.
                #
                # ==========================================

                if (
                    data[
                        "first_crossed_line"
                    ] is None
                ):

                    touched_line = (
                        check_first_touched_line(
                            previous_box,
                            current_box
                        )
                    )

                    if touched_line is not None:

                        data[
                            "first_crossed_line"
                        ] = touched_line

                        data[
                            "movement_status"
                        ] = touched_line

                        data[
                            "crossing_time"
                        ] = datetime.now()

                        data[
                            "identity_enabled"
                        ] = True

                        print()
                        print("=" * 60)
                        print(
                            "FIRST LINE TOUCHED"
                        )
                        print("=" * 60)

                        print(
                            "Vehicle Type :",
                            vehicle_type
                        )

                        print(
                            "Track ID     :",
                            track_id
                        )

                        print(
                            "First Line   :",
                            touched_line
                        )

                        if touched_line == "EXIT":

                            print(
                                "Line Position:",
                                "FIRST / TOP"
                            )

                        else:

                            print(
                                "Line Position:",
                                "SECOND / BOTTOM"
                            )

                        print(
                            "Movement     :",
                            touched_line
                        )

                        print(
                            "OCR          :",
                            "STARTING NOW"
                        )

                        if vehicle_type == "BUS":

                            print(
                                "Validation   :",
                                "PLATE + VEHICLE NUMBER"
                            )

                        else:

                            print(
                                "Validation   :",
                                "PLATE"
                            )

                        print("=" * 60)

                # ==========================================
                # MOVEMENT LABEL
                # ==========================================

                movement_label = (
                    data.get(
                        "movement_status"
                    )
                    or
                    "WAITING FOR FIRST LINE"
                )

                bx1, by1, bx2, by2 = (
                    current_box
                )

                cv2.putText(
                    annotated_frame,
                    movement_label,
                    (
                        bx1,
                        max(
                            45,
                            by1 - 35
                        )
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.60,
                    (0, 255, 255),
                    2
                )

                # ==========================================
                # VEHICLE BOX
                # ==========================================

                cv2.rectangle(
                    annotated_frame,
                    (
                        bx1,
                        by1
                    ),
                    (
                        bx2,
                        by2
                    ),
                    (0, 255, 0),
                    3
                )

                cv2.putText(
                    annotated_frame,
                    (
                        f"{vehicle_type} "
                        f"ID: {track_id}"
                    ),
                    (
                        bx1,
                        max(
                            25,
                            by1 - 10
                        )
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 255, 0),
                    2
                )

                # ==========================================
                # VEHICLE CROP
                # ==========================================

                (
                    vehicle_crop,
                    vehicle_box
                ) = get_safe_crop(
                    frame,
                    box
                )

                if vehicle_crop is None:
                    continue

                bx1, by1, bx2, by2 = (
                    vehicle_box
                )

                # ==========================================
                # PROCESSED
                # ==========================================

                if data[
                    "processed"
                ]:

                    cv2.putText(
                        annotated_frame,
                        "PROCESSED",
                        (
                            bx1,
                            min(
                                frame.shape[0] - 10,
                                by2 + 25
                            )
                        ),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 255, 0),
                        2
                    )

                    continue

                # ==========================================
                # WAITING FOR FIRST LINE
                # ==========================================

                if (
                    OCR_AFTER_FIRST_LINE_ONLY
                    and
                    not data[
                        "identity_enabled"
                    ]
                ):

                    cv2.putText(
                        annotated_frame,
                        "WAITING FOR FIRST LINE",
                        (
                            bx1,
                            min(
                                frame.shape[0] - 10,
                                by2 + 25
                            )
                        ),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.50,
                        (0, 165, 255),
                        2
                    )

                    continue

                # ==========================================
                # OCR ALREADY FINISHED
                # ==========================================

                if data[
                    "ocr_finished"
                ]:

                    continue

                # ==========================================
                # FRAME COUNT
                # ==========================================

                data[
                    "frames"
                ] += 1

                frame_count = data[
                    "frames"
                ]

                # ==========================================
                # WARMUP
                # ==========================================

                if frame_count < WARMUP_FRAMES:

                    cv2.putText(
                        annotated_frame,
                        "DETECTED - WARMING UP",
                        (
                            bx1,
                            min(
                                frame.shape[0] - 10,
                                by2 + 25
                            )
                        ),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 255, 255),
                        2
                    )

                    continue

                # ==========================================
                # OCR LIMIT
                # ==========================================

                if (
                    data[
                        "ocr_attempts"
                    ]
                    >=
                    MAX_OCR_FRAMES
                ):

                    print(
                        f"{vehicle_type} "
                        f"ID {track_id}: "
                        "OCR limit reached."
                    )

                    data[
                        "ocr_finished"
                    ] = True

                    continue

                # ==========================================
                # OCR INTERVAL
                # ==========================================

                if (
                    frame_count
                    -
                    data[
                        "last_ocr_frame"
                    ]
                    <
                    OCR_INTERVAL
                ):

                    continue

                data[
                    "last_ocr_frame"
                ] = frame_count

                data[
                    "ocr_attempts"
                ] += 1

                data[
                    "ocr_started"
                ] = True

                print()
                print("=" * 60)

                print(
                    f"{vehicle_type} DETECTED"
                )

                print(
                    "Track ID:",
                    track_id
                )

                print(
                    "Movement:",
                    data[
                        "movement_status"
                    ]
                )

                print(
                    "OCR attempt:",
                    data[
                        "ocr_attempts"
                    ]
                )

                print("=" * 60)

                # ==========================================
                # PLATE DETECTION
                # ==========================================

                plate_crop = None

                plate_box = None

                plate_confidence = 0.0

                try:

                    print(
                        "Running plate detector..."
                    )

                    plate_results = (
                        detect_plate(
                            vehicle_crop
                        )
                    )

                    (
                        plate_crop,
                        plate_box,
                        plate_confidence
                    ) = get_best_plate_crop(
                        vehicle_crop,
                        plate_results
                    )

                except Exception as e:

                    print(
                        "Plate detector error:",
                        e
                    )

                    plate_results = []

                # ==========================================
                # PLATE OCR
                # ==========================================

                plate_text = ""

                if plate_crop is not None:

                    print(
                        f"Plate detected "
                        f"(confidence: "
                        f"{plate_confidence:.2f})"
                    )

                    if plate_box is not None:

                        px1, py1, px2, py2 = (
                            plate_box
                        )

                        fx1 = (
                            bx1 + px1
                        )

                        fy1 = (
                            by1 + py1
                        )

                        fx2 = (
                            bx1 + px2
                        )

                        fy2 = (
                            by1 + py2
                        )

                        cv2.rectangle(
                            annotated_frame,
                            (
                                fx1,
                                fy1
                            ),
                            (
                                fx2,
                                fy2
                            ),
                            (255, 255, 0),
                            2
                        )

                        cv2.putText(
                            annotated_frame,
                            "PLATE",
                            (
                                fx1,
                                max(
                                    20,
                                    fy1 - 5
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (255, 255, 0),
                            2
                        )

                    print(
                        "Running plate OCR..."
                    )

                    try:

                        plate_text = (
                            read_plate(
                                plate_crop
                            )
                        )

                        plate_text = (
                            clean_result(
                                plate_text
                            )
                        )

                    except Exception as e:

                        print(
                            "Plate OCR error:",
                            e
                        )

                        plate_text = ""

                    print(
                        "Plate OCR:",
                        plate_text
                        if plate_text
                        else
                        "NOT READ"
                    )

                else:

                    print(
                        "Number plate not detected."
                    )

                # ==========================================
                # VEHICLE NUMBER OCR
                # ==========================================

                bus_number = ""

                if vehicle_type == "BUS":

                    print(
                        "Running vehicle number OCR..."
                    )

                    try:

                        bus_number = (
                            read_bus_number(
                                vehicle_crop
                            )
                        )

                        bus_number = (
                            normalize_bus_number(
                                bus_number
                            )
                        )

                    except Exception as e:

                        print(
                            "Vehicle number OCR error:",
                            e
                        )

                        bus_number = ""

                    print(
                        "Vehicle Number OCR:",
                        bus_number
                        if bus_number
                        else
                        "NOT READ"
                    )

                # ==========================================
                # STORE OCR RESULTS
                # ==========================================

                if plate_text:

                    data[
                        "plates"
                    ].append(
                        plate_text
                    )

                    data[
                        "plates"
                    ] = (
                        data[
                            "plates"
                        ][-5:]
                    )

                if bus_number:

                    data[
                        "bus_numbers"
                    ].append(
                        bus_number
                    )

                    data[
                        "bus_numbers"
                    ] = (
                        data[
                            "bus_numbers"
                        ][-5:]
                    )

                # ==========================================
                # STABLE RESULTS
                # ==========================================

                stable_plate = (
                    get_most_common(
                        data[
                            "plates"
                        ]
                    )
                )

                stable_bus_number = (
                    get_most_common(
                        data[
                            "bus_numbers"
                        ]
                    )
                )

                plate_stable = (
                    is_stable(
                        data[
                            "plates"
                        ]
                    )
                )

                bus_number_stable = (
                    is_stable(
                        data[
                            "bus_numbers"
                        ]
                    )
                )

                print(
                    "Stable Plate:",
                    stable_plate
                    if stable_plate
                    else
                    "NONE"
                )

                print(
                    "Stable Vehicle Number:",
                    stable_bus_number
                    if stable_bus_number
                    else
                    "NONE"
                )

                # ==========================================
                # BOTH REQUIRED FOR BUS
                # ==========================================

                if vehicle_type == "BUS":

                    ready_for_classification = (
                        plate_stable
                        and
                        bus_number_stable
                    )

                else:

                    ready_for_classification = (
                        plate_stable
                    )

                # ==========================================
                # WAIT FOR REQUIRED OCR
                # ==========================================

                if not ready_for_classification:

                    if vehicle_type == "BUS":

                        ocr_status = (
                            "OCR: PLATE + VEHICLE NO"
                        )

                    else:

                        ocr_status = (
                            "OCR: PLATE"
                        )

                    cv2.putText(
                        annotated_frame,
                        ocr_status,
                        (
                            bx1,
                            min(
                                frame.shape[0] - 10,
                                by2 + 25
                            )
                        ),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.50,
                        (0, 255, 255),
                        2
                    )

                    continue

                # ==========================================
                # CLASSIFICATION
                # ==========================================

                (
                    classification,
                    matched_data
                ) = classify_vehicle(
                    vehicle_type,
                    stable_plate,
                    stable_bus_number
                )

                # ==========================================
                # OCR FINISHED
                # ==========================================

                data[
                    "ocr_finished"
                ] = True

                data[
                    "classification"
                ] = classification

                data[
                    "matched_data"
                ] = matched_data

                # ==========================================
                # COLLEGE BUS
                # ==========================================

                if (
                    classification
                    ==
                    "COLLEGE_BUS"
                ):

                    movement = (
                        data[
                            "movement_status"
                        ]
                        or
                        "ENTRY"
                    )

                    success = (
                        save_college_bus(
                            frame,
                            track_id,
                            stable_plate,
                            stable_bus_number,
                            matched_data,
                            recent_plates,
                            recent_bus_numbers,
                            current_time,
                            movement=movement,
                            crossing_time=data[
                                "crossing_time"
                            ]
                        )
                    )

                    if success:

                        data[
                            "database_saved"
                        ] = True

                        data[
                            "processed"
                        ] = True

                        atlas_bus_no = (
                            matched_data.get(
                                "bus_no",
                                ""
                            )
                        )

                        atlas_plate = (
                            matched_data.get(
                                "plate",
                                stable_plate
                            )
                        )

                        cv2.putText(
                            annotated_frame,
                            (
                                f"COLLEGE BUS "
                                f"{atlas_bus_no}"
                            ),
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 40,
                                    by2 + 25
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.60,
                            (0, 255, 0),
                            2
                        )

                        cv2.putText(
                            annotated_frame,
                            atlas_plate,
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 10,
                                    by2 + 50
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (0, 255, 0),
                            2
                        )

                        cv2.putText(
                            annotated_frame,
                            movement,
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 10,
                                    by2 + 75
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (0, 255, 0),
                            2
                        )

                    continue

                # ==========================================
                # STAFF
                # ==========================================

                if classification == "STAFF":

                    movement = (
                        data[
                            "movement_status"
                        ]
                        or
                        "ENTRY"
                    )

                    success = (
                        save_staff_detection(
                            frame,
                            track_id,
                            stable_plate,
                            matched_data,
                            recent_plates,
                            current_time,
                            vehicle_type,
                            movement=movement,
                            crossing_time=data[
                                "crossing_time"
                            ]
                        )
                    )

                    if success:

                        data[
                            "processed"
                        ] = True

                        staff_name = (
                            matched_data.get(
                                "staff_name",
                                "STAFF"
                            )
                        )

                        cv2.putText(
                            annotated_frame,
                            "STAFF VEHICLE",
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 40,
                                    by2 + 25
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.60,
                            (255, 255, 0),
                            2
                        )

                        cv2.putText(
                            annotated_frame,
                            staff_name,
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 10,
                                    by2 + 50
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.50,
                            (255, 255, 0),
                            2
                        )

                        cv2.putText(
                            annotated_frame,
                            movement,
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 10,
                                    by2 + 75
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.50,
                            (255, 255, 0),
                            2
                        )

                    continue

                # ==========================================
                # UNKNOWN
                # ==========================================

                if classification == "UNKNOWN":

                    movement = (
                        data[
                            "movement_status"
                        ]
                        or
                        "ENTRY"
                    )

                    success = (
                        save_unknown_detection(
                            frame,
                            track_id,
                            stable_plate,
                            vehicle_type,
                            recent_plates,
                            current_time,
                            movement=movement,
                            crossing_time=data[
                                "crossing_time"
                            ]
                        )
                    )

                    if success:

                        data[
                            "processed"
                        ] = True

                        cv2.putText(
                            annotated_frame,
                            "UNKNOWN VEHICLE",
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 40,
                                    by2 + 25
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.60,
                            (0, 0, 255),
                            2
                        )

                        if stable_plate:

                            cv2.putText(
                                annotated_frame,
                                stable_plate,
                                (
                                    bx1,
                                    min(
                                        frame.shape[0] - 10,
                                        by2 + 50
                                    )
                                ),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.55,
                                (0, 0, 255),
                                2
                            )

                        cv2.putText(
                            annotated_frame,
                            movement,
                            (
                                bx1,
                                min(
                                    frame.shape[0] - 10,
                                    by2 + 75
                                )
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.50,
                            (0, 0, 255),
                            2
                        )

        # ========================================================
        # FINALISE DISAPPEARED TRACKS
        # ========================================================

        for track_id, data in list(
            vehicle_data.items()
        ):

            if data.get(
                "processed",
                False
            ):

                missing_time = (
                    current_time
                    -
                    data.get(
                        "last_seen",
                        current_time
                    )
                )

                if missing_time > 2:

                    vehicle_data.pop(
                        track_id,
                        None
                    )

                continue

            if track_id in current_track_ids:

                continue

            missing_time = (
                current_time
                -
                data.get(
                    "last_seen",
                    current_time
                )
            )

            if (
                missing_time
                <
                TRACK_MISSING_TIMEOUT
            ):

                continue

            # ====================================================
            # NO LINE = NO OCR / NO SAVE
            # ====================================================

            if data.get(
                "first_crossed_line"
            ) is None:

                if missing_time > 2:

                    vehicle_data.pop(
                        track_id,
                        None
                    )

                continue

            vehicle_type = data.get(
                "vehicle_type",
                "VEHICLE"
            )

            stable_plate = (
                get_most_common(
                    data.get(
                        "plates",
                        []
                    )
                )
            )

            stable_bus_number = (
                get_most_common(
                    data.get(
                        "bus_numbers",
                        []
                    )
                )
            )

            classification = data.get(
                "classification"
            )

            matched_data = data.get(
                "matched_data"
            )

            # ====================================================
            # FINAL COLLEGE BUS SAVE
            # ====================================================

            if (
                classification
                ==
                "COLLEGE_BUS"
                and
                matched_data is not None
                and
                not data.get(
                    "database_saved",
                    False
                )
            ):

                movement = (
                    data.get(
                        "movement_status"
                    )
                    or
                    "ENTRY"
                )

                success = (
                    save_college_bus(
                        data[
                            "last_frame"
                        ],
                        track_id,
                        stable_plate,
                        stable_bus_number,
                        matched_data,
                        recent_plates,
                        recent_bus_numbers,
                        current_time,
                        movement=movement,
                        crossing_time=data.get(
                            "crossing_time"
                        )
                    )
                )

                if success:

                    data[
                        "database_saved"
                    ] = True

                    data[
                        "processed"
                    ] = True

            # ====================================================
            # REMOVE OLD TRACK
            # ====================================================

            if (
                data.get(
                    "processed",
                    False
                )
                or
                missing_time > 5
            ):

                vehicle_data.pop(
                    track_id,
                    None
                )

        # ========================================================
        # CLEAN DUPLICATE PLATE MEMORY
        # ========================================================

        for plate, timestamp in list(
            recent_plates.items()
        ):

            if (
                current_time
                -
                timestamp
            ) > DUPLICATE_COOLDOWN:

                recent_plates.pop(
                    plate,
                    None
                )

        # ========================================================
        # CLEAN DUPLICATE BUS NUMBER MEMORY
        # ========================================================

        for bus_no, timestamp in list(
            recent_bus_numbers.items()
        ):

            if (
                current_time
                -
                timestamp
            ) > DUPLICATE_COOLDOWN:

                recent_bus_numbers.pop(
                    bus_no,
                    None
                )

        # ========================================================
        # SEND FRAME TO DASHBOARD
        # ========================================================

        with frame_lock:

            latest_frame = (
                annotated_frame.copy()
            )

        # ========================================================
        # DISPLAY
        # ========================================================

        cv2.imshow(
            "IN/OUT X - Live Camera",
            annotated_frame
        )

        # ========================================================
        # KEYBOARD
        # ========================================================

        key = (
            cv2.waitKey(1)
            &
            0xFF
        )

        # ========================================================
        # RESET LINES
        # ========================================================

        if key == ord("r"):

            line_selection_points.clear()

            line_selection_done = False

            print()
            print("=" * 60)

            print(
                "LINE SELECTION RESET"
            )

            print(
                "Click:"
            )

            print(
                "1 -> EXIT start"
            )

            print(
                "2 -> EXIT end"
            )

            print(
                "3 -> ENTRY start"
            )

            print(
                "4 -> ENTRY end"
            )

            print("=" * 60)

        # ========================================================
        # QUIT
        # ========================================================

        if key == ord("q"):

            break

    # ============================================================
    # RELEASE
    # ============================================================

    camera.release()

    cv2.destroyAllWindows()

    print()
    print("=" * 60)
    print("Camera stopped.")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    start_camera()
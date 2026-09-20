# ============================================================
# INOUTX - LICENSE PLATE DETECTOR
# ============================================================

from pathlib import Path

from ultralytics import YOLO


# ============================================================
# PROJECT PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = (
    BASE_DIR
    / "models"
    / "license_plate_detector.pt"
)


# ============================================================
# CONFIGURATION
# ============================================================

PLATE_CONFIDENCE = 0.20
PLATE_IOU = 0.45
PLATE_IMAGE_SIZE = 640
MAX_DETECTIONS = 5

MIN_ASPECT_RATIO = 1.20
MAX_ASPECT_RATIO = 6.00


# ============================================================
# LOAD MODEL
# ============================================================

print("=" * 60)
print("IN/OUT X - Loading license plate model")
print("Model:", MODEL_PATH)
print("=" * 60)

try:

    plate_model = YOLO(
        str(MODEL_PATH)
    )

    print(
        "License plate model loaded successfully."
    )

except Exception as e:

    print("=" * 60)
    print("LICENSE PLATE MODEL LOAD ERROR")
    print(e)
    print("=" * 60)

    plate_model = None


print("=" * 60)


# ============================================================
# VALIDATE PLATE BOX
# ============================================================

def is_valid_plate_box(
    x1,
    y1,
    x2,
    y2,
    confidence
):

    width = x2 - x1
    height = y2 - y1

    if width <= 0 or height <= 0:
        return False

    aspect_ratio = width / height

    if aspect_ratio < MIN_ASPECT_RATIO:
        return False

    if aspect_ratio > MAX_ASPECT_RATIO:
        return False

    if confidence < PLATE_CONFIDENCE:
        return False

    return True


# ============================================================
# DETECT PLATE INSIDE VEHICLE CROP
# ============================================================

def detect_plate(vehicle_crop):
    """
    Detect number plate inside a vehicle crop.

    Input:
        vehicle_crop

    Output:
        List of dictionaries:

        [
            {
                "box": (x1, y1, x2, y2),
                "confidence": 0.91
            }
        ]

    Coordinates are relative to vehicle_crop.
    """

    if vehicle_crop is None:
        return []

    if getattr(vehicle_crop, "size", 0) == 0:
        return []

    if plate_model is None:
        return []

    try:

        results = plate_model.predict(
            vehicle_crop,
            conf=PLATE_CONFIDENCE,
            iou=PLATE_IOU,
            imgsz=PLATE_IMAGE_SIZE,
            max_det=MAX_DETECTIONS,
            verbose=False,
        )

        if not results:
            return []

        result = results[0]

        if result.boxes is None:
            return []

        if len(result.boxes) == 0:
            return []

        candidates = []

        for index in range(len(result.boxes)):

            try:

                box = result.boxes[index]

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0].tolist()
                )

                confidence = float(
                    box.conf[0].item()
                )

                if not is_valid_plate_box(
                    x1,
                    y1,
                    x2,
                    y2,
                    confidence,
                ):
                    continue

                candidates.append(
                    {
                        "box": (
                            x1,
                            y1,
                            x2,
                            y2,
                        ),
                        "confidence": confidence,
                    }
                )

            except Exception:
                continue

        candidates.sort(
            key=lambda item: item["confidence"],
            reverse=True,
        )

        return candidates

    except Exception as e:

        print(
            "Plate detection error:",
            e
        )

        return []


# ============================================================
# CONVERT VEHICLE-CROP BOX TO FULL-FRAME BOX
# ============================================================

def plate_box_to_frame(
    plate_box,
    vehicle_box
):
    """
    Convert plate coordinates from vehicle crop
    into original camera-frame coordinates.

    plate_box:
        (px1, py1, px2, py2)

    vehicle_box:
        (vx1, vy1, vx2, vy2)
    """

    if not plate_box:
        return None

    if not vehicle_box:
        return None

    try:

        px1, py1, px2, py2 = plate_box

        vx1, vy1, vx2, vy2 = vehicle_box

        return (
            vx1 + px1,
            vy1 + py1,
            vx1 + px2,
            vy1 + py2,
        )

    except Exception:

        return None


# ============================================================
# GET BEST PLATE
# ============================================================

def get_best_plate_detection(
    detections
):

    if not detections:
        return None

    return max(
        detections,
        key=lambda item: item.get(
            "confidence",
            0.0
        )
    )
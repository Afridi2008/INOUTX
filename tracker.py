# ============================================================
# INOUTX - VEHICLE DETECTION + TRACKING
# ============================================================

from ultralytics import YOLO


# ============================================================
# CONFIG
# ============================================================

MODEL_PATH = "models/yolov8n.pt"

# COCO classes
# 2 = car
# 3 = motorcycle
# 5 = bus
# 7 = truck

VEHICLE_CLASSES = [2, 3, 5, 7]

# Lower = detects more distant vehicles
DETECTION_CONFIDENCE = 0.20

IOU_THRESHOLD = 0.45

IMAGE_SIZE = 640


# ============================================================
# LOAD MODEL
# ============================================================

print("=" * 60)
print("Loading YOLO vehicle model...")
print("Model:", MODEL_PATH)
print("=" * 60)

model = YOLO(MODEL_PATH)

print("YOLO model loaded successfully.")
print("=" * 60)


# ============================================================
# VEHICLE TRACKING
# ============================================================

def track_bus(frame):
    """
    Detect and track:

        CAR
        MOTORCYCLE
        BUS
        TRUCK

    ByteTrack gives a persistent ID to each vehicle.
    """

    if frame is None:
        return []

    try:

        results = model.track(
            source=frame,

            # Keep tracking IDs between frames
            persist=True,

            # ByteTrack
            tracker="bytetrack.yaml",

            # Only vehicle classes
            classes=VEHICLE_CLASSES,

            # Detection sensitivity
            conf=DETECTION_CONFIDENCE,

            # NMS IoU
            iou=IOU_THRESHOLD,

            # YOLO input size
            imgsz=IMAGE_SIZE,

            # No unnecessary console output
            verbose=False
        )

        return results

    except Exception as e:

        print("=" * 60)
        print("YOLO TRACKING ERROR")
        print(e)
        print("=" * 60)

        return []
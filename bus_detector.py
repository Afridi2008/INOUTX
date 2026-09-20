from ultralytics import YOLO
import cv2

# Load YOLO model
model = YOLO("models/yolov8n.pt")


def detect_bus(frame):
    results = model(frame)

    for result in results:
        for box in result.boxes:

            cls = int(box.cls[0])

            # COCO dataset la Bus class ID = 5
            if cls == 5:

                x1, y1, x2, y2 = map(int, box.xyxy[0])

                # Green Bounding Box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                cv2.putText(
                    frame,
                    "BUS",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2
                )

    return frame
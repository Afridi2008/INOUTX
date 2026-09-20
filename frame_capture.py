import os
import cv2
from datetime import datetime

# Folder to save captured images
SAVE_FOLDER = "captured_frames"

os.makedirs(SAVE_FOLDER, exist_ok=True)


def save_frame(frame, track_id):
    """
    Save captured frame using tracker ID and current time.
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"Bus_{track_id}_{timestamp}.jpg"

    filepath = os.path.join(SAVE_FOLDER, filename)

    cv2.imwrite(filepath, frame)

    print(f"📸 Frame Saved : {filename}")

    return filepath
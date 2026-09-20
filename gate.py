import cv2

# Virtual Line Position
LINE_Y = 300

# Green Line Color
LINE_COLOR = (0, 255, 0)

# Line Thickness
LINE_THICKNESS = 2


def draw_virtual_line(frame):
    """
    Draw virtual line on the camera frame.
    """

    cv2.line(
        frame,
        (0, LINE_Y),
        (frame.shape[1], LINE_Y),
        LINE_COLOR,
        LINE_THICKNESS
    )

    return frame
# Store processed tracker IDs
processed_ids = set()


def check_line_crossing(track_id, center_y):
    """
    Returns True only once when a bus crosses the virtual line.
    """

    if center_y > LINE_Y and track_id not in processed_ids:
        processed_ids.add(track_id)
        return True

    return False
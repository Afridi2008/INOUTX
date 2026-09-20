from datetime import datetime


def create_metadata(bus_id, plate, image_path):
    """
    Create complete metadata for a detected bus.
    """

    now = datetime.now()

    metadata = {
        "bus_id": bus_id,
        "plate": plate,
        "date": now.strftime("%d-%m-%Y"),
        "time": now.strftime("%I:%M:%S %p"),
        "gate": "Main Gate",
        "camera": "Gate Camera 01",
        "image": image_path
    }

    return metadata
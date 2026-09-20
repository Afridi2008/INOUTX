from datetime import datetime

from mongodb import alerts


def create_notification(
    title,
    message,
    notification_type="info"
):
    """
    Create a notification in MongoDB.
    """

    notification = {
        "title": str(title),
        "message": str(message),
        "type": str(notification_type),
        "created_at": datetime.now(),
        "read": False
    }

    try:

        result = alerts.insert_one(
            notification
        )

        print(
            "Notification created:",
            title
        )

        return str(result.inserted_id)

    except Exception as e:

        print(
            "Notification error:",
            e
        )

        return None
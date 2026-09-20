import os
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from rapidfuzz import process, fuzz


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
MONGO_DB = os.getenv("MONGO_DB", "IN_OUTX")

if not MONGODB_USERNAME:
    raise RuntimeError("MONGODB_USERNAME is missing from .env")

if not MONGODB_PASSWORD:
    raise RuntimeError("MONGODB_PASSWORD is missing from .env")


# ============================================================
# MONGODB ATLAS CONNECTION
# ============================================================

encoded_username = quote_plus(MONGODB_USERNAME)
encoded_password = quote_plus(MONGODB_PASSWORD)

MONGO_URI = (
    f"mongodb+srv://"
    f"{encoded_username}:{encoded_password}"
    f"@cluster0.c2phmz2.mongodb.net/"
    f"?appName=Cluster0"
)

print()
print("=" * 65)
print("IN/OUT X - MongoDB Atlas")
print("=" * 65)
print("Connecting to MongoDB Atlas...")


client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000
)

try:
    client.admin.command("ping")
    print("MongoDB Atlas connected successfully!")
except Exception as e:
    print("MongoDB Atlas connection failed!")
    print(e)
    raise


db = client[MONGO_DB]

print(f"Database : {MONGO_DB}")


# ============================================================
# COLLECTIONS
# ===========================
# =================================
users = db["users"]
email_verifications = db["email_verifications"]
password_resets = db["password_resets"]

college_buses = db["college_buses"]
bus_logs = db["bus_logs"]

staff_vehicles = db["staff_vehicles"]
staff_logs = db["staff_logs"]

# Existing project uses visitor_vehicles for unknown vehicles
visitor_vehicles = db["visitor_vehicles"]
unknown_vehicles = visitor_vehicles
visitor_logs = db["visitor_logs"]

alerts = db["alerts"]
detections = db["detections"]

# Current movement state
vehicle_states = db["vehicle_states"]

# Unified gate crossing history
gate_events = db["gate_events"]


# ============================================================
# NORMALIZATION
# ============================================================

def clean_plate(plate):
    if plate is None:
        return ""

    return (
        str(plate)
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .replace(".", "")
        .replace("_", "")
        .strip()
    )


def clean_bus_number(bus_no):
    if bus_no is None:
        return ""

    value = str(bus_no).strip()

    if value.lower() in {
        "",
        "unknown",
        "none",
        "null"
    }:
        return ""

    return value


# ============================================================
# VEHICLE LOOKUP
# ============================================================

def find_college_bus(plate):
    plate = clean_plate(plate)

    if not plate:
        return None

    bus = college_buses.find_one({
        "plate": plate,
        "status": "ACTIVE"
    })

    if bus:
        print(
            f"COLLEGE BUS FOUND | "
            f"Bus No: {bus.get('bus_no')} | "
            f"Plate: {bus.get('plate')}"
        )

    return bus


def find_bus_by_number(bus_no):
    bus_no = clean_bus_number(bus_no)

    if not bus_no:
        return None

    # Primary schema = bus_no.
    bus = college_buses.find_one({
        "bus_no": bus_no,
        "status": "ACTIVE"
    })

    # Backward compatibility if an old document uses bus_number.
    if bus is None:
        bus = college_buses.find_one({
            "bus_number": bus_no,
            "status": "ACTIVE"
        })

    if bus:
        print(
            f"COLLEGE BUS FOUND BY BUS NUMBER | "
            f"Bus No: {bus.get('bus_no', bus.get('bus_number'))} | "
            f"Plate: {bus.get('plate')}"
        )

    return bus


def find_best_matching_bus(ocr_plate, threshold=80):
    ocr_plate = clean_plate(ocr_plate)

    if not ocr_plate:
        return None

    buses = list(
        college_buses.find({
            "status": "ACTIVE"
        })
    )

    if not buses:
        return None

    plate_map = {}

    for bus in buses:
        plate = clean_plate(
            bus.get("plate", "")
        )

        if plate:
            plate_map[plate] = bus

    if not plate_map:
        return None

    match = process.extractOne(
        ocr_plate,
        list(plate_map.keys()),
        scorer=fuzz.ratio
    )

    if match is None:
        return None

    matched_plate, score, _ = match

    print(
        f"FUZZY BUS MATCH | "
        f"OCR={ocr_plate} | "
        f"MATCH={matched_plate} | "
        f"SCORE={score:.2f}%"
    )

    if score >= threshold:
        return plate_map[matched_plate]

    return None


def find_staff_vehicle(plate):
    plate = clean_plate(plate)

    if not plate:
        return None

    vehicle = staff_vehicles.find_one({
        "plate": plate,
        "status": "ACTIVE"
    })

    if vehicle:
        print(
            f"STAFF VEHICLE FOUND | "
            f"Plate: {plate}"
        )

    return vehicle


# ============================================================
# IDENTIFY VEHICLE
# ============================================================

def identify_vehicle(
    plate="",
    bus_number="",
    detected_vehicle_type="UNKNOWN"
):
    plate = clean_plate(plate)
    bus_number = clean_bus_number(bus_number)

    # --------------------------------------------------------
    # 1. COLLEGE BUS BY PLATE
    # --------------------------------------------------------

    if plate:
        bus = find_college_bus(plate)

        if bus:
            return {
                "category": "BUS",
                "verified": True,
                "data": bus
            }

        # Fuzzy match only after exact match fails.
        bus = find_best_matching_bus(
            plate,
            threshold=80
        )

        if bus:
            return {
                "category": "BUS",
                "verified": True,
                "data": bus
            }

    # --------------------------------------------------------
    # 2. COLLEGE BUS BY BODY NUMBER
    # --------------------------------------------------------

    if (
        detected_vehicle_type == "BUS"
        and
        bus_number
    ):
        bus = find_bus_by_number(
            bus_number
        )

        if bus:
            return {
                "category": "BUS",
                "verified": True,
                "data": bus
            }

    # --------------------------------------------------------
    # 3. STAFF VEHICLE
    # --------------------------------------------------------

    if plate:
        staff = find_staff_vehicle(
            plate
        )

        if staff:
            return {
                "category": "STAFF",
                "verified": True,
                "data": staff
            }

    # --------------------------------------------------------
    # 4. UNKNOWN
    # --------------------------------------------------------

    return {
        "category": "UNKNOWN",
        "verified": False,
        "data": None
    }


# ============================================================
# GATE EVENT
# ============================================================

def insert_gate_event(data):
    if not isinstance(data, dict):
        raise TypeError(
            "Gate event data must be a dictionary."
        )

    result = gate_events.insert_one(
        data
    )

    print(
        f"GATE EVENT SAVED | "
        f"{result.inserted_id}"
    )

    return result.inserted_id


# ============================================================
# BUS LOG
# ============================================================

def insert_bus_log(data):
    if not isinstance(data, dict):
        raise TypeError(
            "Bus log data must be a dictionary."
        )

    result = bus_logs.insert_one(
        data
    )

    print(
        f"BUS LOG SAVED | "
        f"{result.inserted_id}"
    )

    return result.inserted_id


# ============================================================
# STAFF LOG
# ============================================================

def save_staff_vehicle(data):
    if not isinstance(data, dict):
        raise TypeError(
            "Staff vehicle data must be a dictionary."
        )

    result = staff_logs.insert_one(
        data
    )

    print(
        f"STAFF LOG SAVED | "
        f"{result.inserted_id}"
    )

    return result.inserted_id


# ============================================================
# UNKNOWN VEHICLE
# ============================================================

def save_unknown_vehicle(data):
    if not isinstance(data, dict):
        raise TypeError(
            "Unknown vehicle data must be a dictionary."
        )

    result = unknown_vehicles.insert_one(
        data
    )

    print(
        f"UNKNOWN VEHICLE SAVED | "
        f"{result.inserted_id}"
    )

    return result.inserted_id


# ============================================================
# CURRENT VEHICLE STATE
# ============================================================

def get_vehicle_state(vehicle_key):
    if not vehicle_key:
        return None

    return vehicle_states.find_one({
        "vehicle_key": vehicle_key
    })


def get_current_direction(vehicle_key):
    state = get_vehicle_state(
        vehicle_key
    )

    if not state:
        return None

    return state.get(
        "current_status"
    )


def calculate_gate2_direction(
    vehicle_key,
    first_direction="ENTRY"
):
    """
    Gate 2 has only ONE camera.

    First registered crossing:
        ENTRY

    Next:
        EXIT

    Next:
        ENTRY

    Next:
        EXIT
    """

    current_status = get_current_direction(
        vehicle_key
    )

    if current_status == "INSIDE":
        return "EXIT"

    if current_status == "OUTSIDE":
        return "ENTRY"

    # First-ever detection.
    return first_direction


def update_vehicle_state(
    vehicle_key,
    category,
    plate,
    bus_number,
    direction,
    gate,
    camera_id,
    event_id=None
):
    if not vehicle_key:
        return None

    if direction == "ENTRY":
        current_status = "INSIDE"

    elif direction == "EXIT":
        current_status = "OUTSIDE"

    else:
        current_status = "UNKNOWN"

    now = datetime.now()

    update = {
        "$set": {
            "vehicle_key": vehicle_key,
            "category": category,
            "plate": clean_plate(plate),
            "bus_no": clean_bus_number(bus_number),
            "current_status": current_status,
            "last_direction": direction,
            "last_gate": gate,
            "last_camera": camera_id,
            "last_event_id": event_id,
            "last_seen": now
        },
        "$setOnInsert": {
            "created_at": now
        },
        "$inc": {
            "crossing_count": 1
        }
    }

    result = vehicle_states.update_one(
        {
            "vehicle_key": vehicle_key
        },
        update,
        upsert=True
    )

    return result


# ============================================================
# COMPLETE MOVEMENT SAVE
# ============================================================

def save_vehicle_movement(
    *,
    category,
    plate,
    bus_number,
    direction,
    gate,
    camera_id,
    vehicle_type,
    track_id,
    image_path,
    vehicle_data=None
):
    plate = clean_plate(plate)
    bus_number = clean_bus_number(
        bus_number
    )

    now = datetime.now()

    # --------------------------------------------------------
    # Stable identity
    # --------------------------------------------------------

    if plate:
        vehicle_key = f"PLATE:{plate}"

    elif (
        category == "BUS"
        and
        bus_number
    ):
        vehicle_key = f"BUS:{bus_number}"

    else:
        vehicle_key = (
            f"{gate}:{camera_id}:"
            f"TRACK:{track_id}"
        )

    # --------------------------------------------------------
    # Base event
    # --------------------------------------------------------

    event = {
        "vehicle_key": vehicle_key,

        "category": category,

        "vehicle_type": vehicle_type,

        "plate": plate,

        "bus_no": bus_number,

        "direction": direction,

        "gate": gate,

        "camera_id": camera_id,

        "track_id": track_id,

        "image": image_path,

        "date": now.strftime(
            "%d-%m-%Y"
        ),

        "time": now.strftime(
            "%I:%M:%S %p"
        ),

        "timestamp": now,

        "verified": (
            category != "UNKNOWN"
        )
    }

    # --------------------------------------------------------
    # Add registered bus details
    # --------------------------------------------------------

    if (
        category == "BUS"
        and
        vehicle_data
    ):
        event["bus_id"] = (
            vehicle_data.get(
                "bus_id"
            )
        )

        event["bus_no"] = (
            vehicle_data.get(
                "bus_no",
                vehicle_data.get(
                    "bus_number",
                    bus_number
                )
            )
        )

        event["driver"] = (
            vehicle_data.get(
                "driver"
            )
        )

        event["route"] = (
            vehicle_data.get(
                "route"
            )
        )

    # --------------------------------------------------------
    # Add staff details
    # --------------------------------------------------------

    if (
        category == "STAFF"
        and
        vehicle_data
    ):
        event["staff_name"] = (
            vehicle_data.get(
                "staff_name"
            )
        )

        event["staff_id"] = (
            vehicle_data.get(
                "staff_id"
            )
        )

        event["staff_vehicle_type"] = (
            vehicle_data.get(
                "vehicle_type"
            )
        )

    # --------------------------------------------------------
    # Save unified event
    # --------------------------------------------------------

    event_id = insert_gate_event(
        event
    )

    # --------------------------------------------------------
    # Save category-specific log
    # --------------------------------------------------------

    if category == "BUS":

        bus_log = dict(event)

        bus_log["event_id"] = event_id

        insert_bus_log(
            bus_log
        )

    elif category == "STAFF":

        staff_log = dict(event)

        staff_log["event_id"] = event_id

        save_staff_vehicle(
            staff_log
        )

    else:

        unknown_log = dict(event)

        unknown_log["event_id"] = event_id

        save_unknown_vehicle(
            unknown_log
        )

    # --------------------------------------------------------
    # Update current state
    # --------------------------------------------------------

    update_vehicle_state(
        vehicle_key=vehicle_key,
        category=category,
        plate=plate,
        bus_number=bus_number,
        direction=direction,
        gate=gate,
        camera_id=camera_id,
        event_id=event_id
    )

    print()
    print("=" * 65)
    print("MOVEMENT SAVED")
    print("=" * 65)
    print(f"Category   : {category}")
    print(f"Vehicle    : {vehicle_type}")
    print(f"Plate      : {plate or 'UNKNOWN'}")
    print(f"Bus No     : {bus_number or 'UNKNOWN'}")
    print(f"Direction  : {direction}")
    print(f"Gate       : {gate}")
    print(f"Camera     : {camera_id}")
    print(f"Event ID   : {event_id}")
    print("=" * 65)

    return event_id


# ============================================================
# DUPLICATE / RECENT EVENT CHECK
# ============================================================

def recent_event_exists(
    vehicle_key,
    gate,
    camera_id,
    cooldown_seconds=20
):
    if not vehicle_key:
        return False

    cutoff = (
        datetime.now()
        .timestamp()
        -
        cooldown_seconds
    )

    cutoff_dt = datetime.fromtimestamp(
        cutoff
    )

    found = gate_events.find_one({
        "vehicle_key": vehicle_key,
        "gate": gate,
        "camera_id": camera_id,
        "timestamp": {
            "$gte": cutoff_dt
        }
    })

    return found is not None


# ============================================================
# GET LOGS
# ============================================================

def get_all_logs():
    return list(
        gate_events.find()
        .sort(
            "timestamp",
            DESCENDING
        )
    )


def get_all_bus_logs():
    return list(
        bus_logs.find()
        .sort(
            "timestamp",
            DESCENDING
        )
    )


def get_all_staff_logs():
    return list(
        staff_logs.find()
        .sort(
            "timestamp",
            DESCENDING
        )
    )


def get_all_unknown_vehicles():
    return list(
        unknown_vehicles.find()
        .sort(
            "timestamp",
            DESCENDING
        )
    )


def get_all_college_buses():
    return list(
        college_buses.find()
        .sort(
            "bus_no",
            ASCENDING
        )
    )


def get_active_college_buses():
    return list(
        college_buses.find({
            "status": "ACTIVE"
        }).sort(
            "bus_no",
            ASCENDING
        )
    )


def get_all_staff_vehicles():
    return list(
        staff_vehicles.find()
        .sort(
            "_id",
            DESCENDING
        )
    )


def get_all_detections():
    return list(
        detections.find()
        .sort(
            "_id",
            DESCENDING
        )
    )


# ============================================================
# DASHBOARD
# ============================================================

def get_dashboard_stats():
    return {
        "total_buses":
            college_buses.count_documents({
                "status": "ACTIVE"
            }),

        "total_bus_logs":
            bus_logs.count_documents({}),

        "total_staff_vehicles":
            staff_vehicles.count_documents({
                "status": "ACTIVE"
            }),

        "total_unknown_vehicles":
            unknown_vehicles.count_documents({}),

        "total_gate_events":
            gate_events.count_documents({})
    }


# ============================================================
# INDEXES
# ============================================================

def create_indexes():
    try:

        college_buses.create_index(
            [
                ("plate", ASCENDING)
            ]
        )

        college_buses.create_index(
            [
                ("bus_no", ASCENDING)
            ]
        )

        staff_vehicles.create_index(
            [
                ("plate", ASCENDING)
            ]
        )

        gate_events.create_index(
            [
                ("vehicle_key", ASCENDING),
                ("timestamp", DESCENDING)
            ]
        )

        gate_events.create_index(
            [
                ("gate", ASCENDING),
                ("camera_id", ASCENDING),
                ("timestamp", DESCENDING)
            ]
        )

        vehicle_states.create_index(
            [
                ("vehicle_key", ASCENDING)
            ],
            unique=True
        )

        print(
            "MongoDB indexes ready."
        )

    except Exception as e:
        print(
            f"Index creation warning: {e}"
        )


# ============================================================
# TEST CONNECTION
# ============================================================

def test_connection():

    try:

        client.admin.command(
            "ping"
        )

        print()
        print("=" * 65)
        print("IN/OUT X - ATLAS TEST")
        print("=" * 65)
        print(
            "MongoDB Atlas : OK"
        )
        print(
            f"Database      : {db.name}"
        )

        print()
        print("Collections:")

        for name in db.list_collection_names():
            print(
                f"  - {name}"
            )

        print("=" * 65)

        return True

    except Exception as e:

        print(
            "MongoDB Atlas : FAILED"
        )

        print(e)

        return False


# ============================================================
# STARTUP
# ============================================================

create_indexes()


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    test_connection()

    print()
    print("Registered college buses:")
    print("-" * 65)

    for bus in college_buses.find(
        {},
        {
            "_id": 0
        }
    ):
        print(bus)

    print("-" * 65)
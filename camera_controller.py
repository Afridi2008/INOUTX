import os
import sys
import subprocess
import threading

from flask import Flask, jsonify
from flask_cors import CORS


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = os.path.dirname(
    os.path.abspath(__file__)
)

CAMERA_FILE = os.path.join(
    PROJECT_ROOT,
    "camera.py"
)

PYTHON_EXE = sys.executable


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

CORS(
    app,
    origins="*"
)


# ============================================================
# CAMERA PROCESS
# ============================================================

camera_process = None

camera_lock = threading.Lock()


# ============================================================
# START CAMERA
# ============================================================

@app.route(
    "/start",
    methods=["POST"]
)
def start_camera():

    global camera_process

    with camera_lock:

        # ----------------------------------------------------
        # Check existing process
        # ----------------------------------------------------

        if (
            camera_process is not None
            and camera_process.poll() is None
        ):

            return jsonify({
                "success": True,
                "running": True,
                "message": "Camera is already running."
            })


        # ----------------------------------------------------
        # Check camera.py
        # ----------------------------------------------------

        if not os.path.isfile(CAMERA_FILE):

            return jsonify({
                "success": False,
                "running": False,
                "error": (
                    "camera.py was not found."
                )
            }), 404


        # ----------------------------------------------------
        # Start camera.py
        # ----------------------------------------------------

        try:

            camera_process = subprocess.Popen(
                [
                    PYTHON_EXE,
                    CAMERA_FILE
                ],
                cwd=PROJECT_ROOT
            )

            return jsonify({
                "success": True,
                "running": True,
                "message": "camera.py started successfully."
            })

        except Exception as e:

            camera_process = None

            return jsonify({
                "success": False,
                "running": False,
                "error": str(e)
            }), 500


# ============================================================
# CAMERA STATUS
# ============================================================

@app.route(
    "/status",
    methods=["GET"]
)
def camera_status():

    global camera_process

    if (
        camera_process is not None
        and camera_process.poll() is None
    ):

        return jsonify({
            "success": True,
            "running": True,
            "message": "Camera is running."
        })


    return jsonify({
        "success": True,
        "running": False,
        "message": "Camera is not running."
    })


# ============================================================
# STOP CAMERA
# ============================================================

@app.route(
    "/stop",
    methods=["POST"]
)
def stop_camera():

    global camera_process

    with camera_lock:

        if (
            camera_process is None
            or camera_process.poll() is not None
        ):

            camera_process = None

            return jsonify({
                "success": True,
                "running": False,
                "message": "Camera is already stopped."
            })


        try:

            camera_process.terminate()

            camera_process.wait(
                timeout=5
            )

        except Exception:

            try:
                camera_process.kill()
            except Exception:
                pass

        finally:

            camera_process = None


        return jsonify({
            "success": True,
            "running": False,
            "message": "Camera stopped."
        })


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("IN/OUT X CAMERA CONTROLLER")
    print("=" * 60)
    print("Camera file :", CAMERA_FILE)
    print("Python      :", PYTHON_EXE)
    print("Controller  : http://127.0.0.1:8765")
    print("=" * 60)

    app.run(
        host="127.0.0.1",
        port=8765,
        debug=False
    )
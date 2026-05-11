"""
ejb_test_py — Flask demo app using the EndPointBlank Python library.

Endpoints
---------
GET    /schools                             List all schools.
POST   /schools                             Add a school.
DELETE /schools/<id>                        Remove a school.

GET    /classes                             List all classes.
POST   /classes                             Add a class.
DELETE /classes/<id>                        Remove a class.

POST   /classes/<id>/students               Add a student to a class.
DELETE /classes/<id>/students/<student_id>  Remove a student from a class.

GET    /errors                              Intentionally raises a RuntimeError.

All routes are protected by @authorized (EndPointBlank authorization check).
The ReportInteractionMiddleware wraps the WSGI app to capture every request
and response and forward them to the EndPointBlank ingest service.
"""

import logging
import subprocess

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from flask import Flask, jsonify, request

import end_point_blank as epb
from end_point_blank.configuration import LogMode
from end_point_blank.flask.authorized import authorized
from end_point_blank.flask.versioned import versioned
from end_point_blank.flask.endpoint_registrar import register_flask_endpoints
from end_point_blank.middleware.report_interaction import ReportInteractionMiddleware
from end_point_blank.unauthorized_error import UnauthorizedError
from end_point_blank.writers.log_writer import LogWriter

import data as db

# ---------------------------------------------------------------------------
# Configure EndPointBlank
# ---------------------------------------------------------------------------

def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=__file__[:__file__.rfind("/")]
        ).decode().strip()
    except Exception:
        return "0"


epb.configure(
    base_url="http://localhost:4001",
    app_name="ejb-test-py",
    environment="development",
    client_id="HyxhlEx4nT0cUIP9two3sbRiWbJGn+Iv",
    client_secret="6T+yIBMK6N63DpyoOxd0xkUK3ys6PbuV7azeYW4eJIHtm/5u26tXzAEPw1JmZwlJ",
    application_version=_git_commit(),
    log_mode=LogMode.DELAYED,
)

epb.Configuration().log_base_url = "http://localhost:4001"

# ---------------------------------------------------------------------------
# Flask app + middleware
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.wsgi_app = ReportInteractionMiddleware(app.wsgi_app)


@app.errorhandler(UnauthorizedError)
def handle_unauthorized(exc):
    return jsonify(error="Unauthorized"), 401


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@app.route("/status", methods=["GET"])
def status():
    return "ok", 200


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

@app.route("/schools", methods=["GET"])
@authorized
@versioned(["1"], state="Current")
def list_schools():
    LogWriter.info("Fetching schools list")
    return jsonify(schools=db.list_schools())


@app.route("/schools", methods=["POST"])
@authorized
@versioned(["1"], state="Current")
def create_school():
    body = request.get_json(silent=True) or {}
    name     = body.get("name", "").strip()
    type_    = body.get("type", "").strip()
    location = body.get("location", "").strip()

    if not name:
        return jsonify(error="name is required"), 422

    school = db.add_school(name, type_, location)
    LogWriter.info(f"Added school: {name}")
    return jsonify(school=school), 201


@app.route("/schools/<int:school_id>", methods=["DELETE"])
@authorized
@versioned(["1"], state="Current")
def delete_school(school_id: int):
    removed = db.remove_school(school_id)
    if not removed:
        return jsonify(error="School not found"), 404
    LogWriter.info(f"Removed school id: {school_id}")
    return jsonify(message="School removed")


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

@app.route("/classes", methods=["GET"])
@authorized
@versioned(["1"], state="Current")
def list_classes():
    LogWriter.info("Fetching classes list")
    return jsonify(classes=db.list_classes())


@app.route("/classes", methods=["POST"])
@authorized
@versioned(["1"], state="Current")
def create_class():
    body = request.get_json(silent=True) or {}
    name        = body.get("name", "").strip()
    grade       = body.get("grade", "").strip()
    teacher_id  = body.get("teacher_id")
    school_year = body.get("school_year", "").strip()

    if not name:
        return jsonify(error="name is required"), 422

    cls = db.add_class(name, grade, teacher_id, school_year)
    LogWriter.info(f"Added class: {name}")
    return jsonify(**{"class": cls}), 201


@app.route("/classes/<int:class_id>", methods=["DELETE"])
@authorized
@versioned(["1"], state="Current")
def delete_class(class_id: int):
    removed = db.remove_class(class_id)
    if not removed:
        return jsonify(error="Class not found"), 404
    LogWriter.info(f"Removed class id: {class_id}")
    return jsonify(message="Class removed")


# ---------------------------------------------------------------------------
# Class membership
# ---------------------------------------------------------------------------

@app.route("/classes/<int:class_id>/students", methods=["POST"])
@authorized
@versioned(["1"], state="Current")
def add_student(class_id: int):
    body       = request.get_json(silent=True) or {}
    student_id = body.get("student_id")

    if student_id is None:
        return jsonify(error="student_id is required"), 422

    cls, err = db.add_student_to_class(class_id, int(student_id))
    if err:
        status = 404 if err == "Class not found" else 422
        return jsonify(error=err), status

    LogWriter.info(f"Added student {student_id} to class {class_id}")
    return jsonify(**{"class": cls}), 201


@app.route("/classes/<int:class_id>/students/<int:student_id>", methods=["DELETE"])
@authorized
@versioned(["1"], state="Current")
def remove_student(class_id: int, student_id: int):
    cls, err = db.remove_student_from_class(class_id, student_id)
    if err:
        status = 404 if err == "Class not found" else 422
        return jsonify(error=err), status

    LogWriter.info(f"Removed student {student_id} from class {class_id}")
    return jsonify(**{"class": cls})


# ---------------------------------------------------------------------------
# Errors — intentionally raises to exercise error tracking
# ---------------------------------------------------------------------------

@app.route("/errors", methods=["GET"])
@authorized
@versioned(["1"], state="Current")
def trigger_error():
    raise RuntimeError("This is a test error for error tracking.")


# ---------------------------------------------------------------------------
# Endpoint registration (runs at import time for gunicorn workers)
# ---------------------------------------------------------------------------

with app.app_context():
    register_flask_endpoints(app)


# ---------------------------------------------------------------------------
# Entry point (dev server fallback)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(port=3002)

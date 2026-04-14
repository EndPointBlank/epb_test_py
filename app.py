"""
ejb_test_py — Flask demo app using the EndPointBlank Python library.

Endpoints
---------
GET /facilities            List all facilities (schools).
GET /facilities/<id>/rooms Rooms belonging to a specific facility.
GET /errors                Intentionally raises a RuntimeError to exercise
                           EndPointBlank error tracking.

All routes are protected by @authorized (EndPointBlank authorization check).
The ReportInteractionMiddleware wraps the WSGI app to capture every request
and response and forward them to the EndPointBlank ingest service.

Equivalent to epb_test_rails in structure and purpose.
"""

from flask import Flask, jsonify

import end_point_blank as epb
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

epb.configure(
    base_url="http://localhost:4001",
    app_name="ejb-test-py",
    environment="development",
    client_id="HyxhlEx4nT0cUIP9two3sbRiWbJGn+Iv",
    client_secret="6T+yIBMK6N63DpyoOxd0xkUK3ys6PbuV7azeYW4eJIHtm/5u26tXzAEPw1JmZwlJ",
)

# Patch log_base_url directly (configure() doesn't expose it yet)
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
# Facilities
# ---------------------------------------------------------------------------

@app.route("/facilities", methods=["GET"])
@authorized
@versioned(["1"], state="Current")
def list_facilities():
    """Returns all facilities."""
    LogWriter.info("Fetching facilities list")
    return jsonify(facilities=db.FACILITIES)


@app.route("/facilities/<int:facility_id>/rooms", methods=["GET"])
@authorized
@versioned(["1"], state="Current")
def list_rooms(facility_id: int):
    """Returns all rooms belonging to the given facility."""
    facility = db.get_facility(facility_id)
    if facility is None:
        return jsonify(error=f"Facility {facility_id} not found"), 404

    LogWriter.info("Fetching rooms for facility", {"facility_id": facility_id})
    rooms = db.get_rooms_for_facility(facility_id)
    return jsonify(facility=facility, rooms=rooms)


# ---------------------------------------------------------------------------
# Errors — intentionally raises to exercise error tracking
# ---------------------------------------------------------------------------

@app.route("/errors", methods=["GET"])
@authorized
@versioned(["1"], state="Current")
def trigger_error():
    """Raises a RuntimeError to test EndPointBlank error reporting."""
    raise RuntimeError("This is a test error for error tracking.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        register_flask_endpoints(app)
    app.run(port=3002, debug=True)

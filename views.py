import json
import logging
import os
import subprocess

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import end_point_blank as epb
from end_point_blank.configuration import LogMode
from end_point_blank.django.decorators import authorized
from end_point_blank.django.versioned import versioned
from end_point_blank.unauthorized_error import UnauthorizedError
from end_point_blank.writers.log_writer import LogWriter

import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configure EndPointBlank
# ---------------------------------------------------------------------------

def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__)
        ).decode().strip()
    except Exception:
        return "0"


INTAKE_URL = os.environ.get("INTAKE_API_URL", "http://localhost:4001")

epb.configure(
    base_url=INTAKE_URL,
    app_name="ejb-test-py",
    environment=os.environ.get("DJANGO_ENV", "development"),
    client_id="Sb3PyThONd8EvPmQnLuTwFc4YjHgNvOq",
    client_secret="xJ4pQmA7dN3sNkR2tE6bXeJiW0aFzGoBMaVnQkDpEyHwIlZcSxrUfOgtXu9P1J8",
    application_version=_git_commit(),
    log_mode=LogMode.DELAYED,
)

epb.Configuration().log_base_url = INTAKE_URL


# ---------------------------------------------------------------------------
# Error handler helper
# ---------------------------------------------------------------------------

def _unauthorized_handler(request, exc):
    return JsonResponse({"error": "Unauthorized"}, status=401)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def status(request):
    return JsonResponse({"status": "ok"}, status=200)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def schools(request):
    try:
        if request.method == "GET":
            return _list_schools(request)
        return _create_school(request)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _list_schools(request):
    LogWriter.info("Fetching schools list")
    return JsonResponse({"schools": db.list_schools()})


@authorized
@versioned(["1"], state="Current")
def _create_school(request):
    body = json.loads(request.body or b"{}") if request.body else {}
    name = body.get("name", "").strip()
    type_ = body.get("type", "").strip()
    location = body.get("location", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=422)
    school = db.add_school(name, type_, location)
    LogWriter.info(f"Added school: {name}")
    return JsonResponse({"school": school}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def school(request, school_id):
    try:
        return _delete_school(request, school_id)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _delete_school(request, school_id):
    removed = db.remove_school(school_id)
    if not removed:
        return JsonResponse({"error": "School not found"}, status=404)
    LogWriter.info(f"Removed school id: {school_id}")
    return JsonResponse({"message": "School removed"})


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def classes(request):
    try:
        if request.method == "GET":
            return _list_classes(request)
        return _create_class(request)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _list_classes(request):
    LogWriter.info("Fetching classes list")
    return JsonResponse({"classes": db.list_classes()})


@authorized
@versioned(["1"], state="Current")
def _create_class(request):
    body = json.loads(request.body or b"{}") if request.body else {}
    name = body.get("name", "").strip()
    grade = body.get("grade", "").strip()
    teacher_id = body.get("teacher_id")
    school_year = body.get("school_year", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=422)
    cls = db.add_class(name, grade, teacher_id, school_year)
    LogWriter.info(f"Added class: {name}")
    return JsonResponse({"class": cls}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def single_class(request, class_id):
    try:
        return _delete_class(request, class_id)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _delete_class(request, class_id):
    removed = db.remove_class(class_id)
    if not removed:
        return JsonResponse({"error": "Class not found"}, status=404)
    LogWriter.info(f"Removed class id: {class_id}")
    return JsonResponse({"message": "Class removed"})


# ---------------------------------------------------------------------------
# Class membership
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def class_students(request, class_id):
    try:
        return _add_student(request, class_id)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _add_student(request, class_id):
    body = json.loads(request.body or b"{}") if request.body else {}
    student_id = body.get("student_id")
    if student_id is None:
        return JsonResponse({"error": "student_id is required"}, status=422)
    cls, err = db.add_student_to_class(class_id, int(student_id))
    if err:
        status = 404 if err == "Class not found" else 422
        return JsonResponse({"error": err}, status=status)
    LogWriter.info(f"Added student {student_id} to class {class_id}")
    return JsonResponse({"class": cls}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def class_student(request, class_id, student_id):
    try:
        return _remove_student(request, class_id, student_id)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _remove_student(request, class_id, student_id):
    cls, err = db.remove_student_from_class(class_id, student_id)
    if err:
        status = 404 if err == "Class not found" else 422
        return JsonResponse({"error": err}, status=status)
    LogWriter.info(f"Removed student {student_id} from class {class_id}")
    return JsonResponse({"class": cls})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def errors(request):
    try:
        return _trigger_error(request)
    except UnauthorizedError:
        return JsonResponse({"error": "Unauthorized"}, status=401)


@authorized
@versioned(["1"], state="Current")
def _trigger_error(request):
    raise RuntimeError("This is a test error for error tracking.")

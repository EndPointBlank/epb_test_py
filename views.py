import json
import os
import subprocess

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import end_point_blank as epb
from end_point_blank.configuration import LogMode
from end_point_blank.django import authorized
from end_point_blank.django.versioned import versioned

import db

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
# Status
# ---------------------------------------------------------------------------

def status(request):
    return JsonResponse({"status": "ok"}, status=200)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@authorized
def schools(request):
    if request.method == "GET":
        return _list_schools(request)
    return _create_school(request)


@versioned(["1"], state="Current")
def _list_schools(request):
    return JsonResponse({"schools": db.list_schools()})


@versioned(["1"], state="Current")
def _create_school(request):
    body = json.loads(request.body or b"{}") if request.body else {}
    name = body.get("name", "").strip()
    type_ = body.get("type", "").strip()
    location = body.get("location", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=422)
    school = db.add_school(name, type_, location)
    return JsonResponse({"school": school}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
@authorized
def school(request, school_id):
    return _delete_school(request, school_id)


@versioned(["1"], state="Current")
def _delete_school(request, school_id):
    removed = db.remove_school(school_id)
    if not removed:
        return JsonResponse({"error": "School not found"}, status=404)
    return JsonResponse({"message": "School removed"})


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@authorized
def classes(request):
    if request.method == "GET":
        return _list_classes(request)
    return _create_class(request)


@versioned(["1"], state="Current")
def _list_classes(request):
    return JsonResponse({"classes": db.list_classes()})


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
    return JsonResponse({"class": cls}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
@authorized
def single_class(request, class_id):
    return _delete_class(request, class_id)


@versioned(["1"], state="Current")
def _delete_class(request, class_id):
    removed = db.remove_class(class_id)
    if not removed:
        return JsonResponse({"error": "Class not found"}, status=404)
    return JsonResponse({"message": "Class removed"})


# ---------------------------------------------------------------------------
# Class membership
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
@authorized
def class_students(request, class_id):
    return _add_student(request, class_id)


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
    return JsonResponse({"class": cls}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
@authorized
def class_student(request, class_id, student_id):
    return _remove_student(request, class_id, student_id)


@versioned(["1"], state="Current")
def _remove_student(request, class_id, student_id):
    cls, err = db.remove_student_from_class(class_id, student_id)
    if err:
        status = 404 if err == "Class not found" else 422
        return JsonResponse({"error": err}, status=status)
    return JsonResponse({"class": cls})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
@authorized
def errors(request):
    return _trigger_error(request)


@versioned(["1"], state="Current")
def _trigger_error(request):
    raise RuntimeError("This is a test error for error tracking.")

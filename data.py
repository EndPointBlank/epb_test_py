"""
In-memory data store for the ejb_test_py demo app.

Schools have: name, type, location.
Classes have: name, grade, teacher_id, school_year, and a list of student_ids.
"""

from threading import Lock

_lock = Lock()

_schools = [
    {"id": 1, "name": "Lincoln Elementary",    "type": "Elementary", "location": "Springfield, IL"},
    {"id": 2, "name": "Westview Middle School", "type": "Middle",     "location": "Shelbyville, IL"},
    {"id": 3, "name": "Riverside High School",  "type": "High",       "location": "Capital City, IL"},
]

_classes = [
    {"id": 1, "name": "Math 101",    "grade": "3rd", "teacher_id": 1, "school_year": "2025-2026", "student_ids": [1, 2]},
    {"id": 2, "name": "English 201", "grade": "7th", "teacher_id": 2, "school_year": "2025-2026", "student_ids": [3]},
]

_next_school_id = 4
_next_class_id  = 3


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

def list_schools():
    with _lock:
        return list(_schools)


def add_school(name: str, type_: str, location: str) -> dict:
    global _next_school_id
    with _lock:
        school = {"id": _next_school_id, "name": name, "type": type_, "location": location}
        _schools.append(school)
        _next_school_id += 1
        return school


def remove_school(school_id: int):
    global _schools
    with _lock:
        before = len(_schools)
        _schools = [s for s in _schools if s["id"] != school_id]
        return len(_schools) < before


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

def list_classes():
    with _lock:
        return list(_classes)


def add_class(name: str, grade: str, teacher_id: int, school_year: str) -> dict:
    global _next_class_id
    with _lock:
        cls = {
            "id": _next_class_id,
            "name": name,
            "grade": grade,
            "teacher_id": teacher_id,
            "school_year": school_year,
            "student_ids": [],
        }
        _classes.append(cls)
        _next_class_id += 1
        return cls


def remove_class(class_id: int) -> bool:
    global _classes
    with _lock:
        before = len(_classes)
        _classes = [c for c in _classes if c["id"] != class_id]
        return len(_classes) < before


def _find_class(class_id: int):
    return next((c for c in _classes if c["id"] == class_id), None)


def add_student_to_class(class_id: int, student_id: int):
    with _lock:
        cls = _find_class(class_id)
        if cls is None:
            return None, "Class not found"
        if student_id in cls["student_ids"]:
            return None, "Student already in class"
        cls["student_ids"].append(student_id)
        return cls, None


def remove_student_from_class(class_id: int, student_id: int):
    with _lock:
        cls = _find_class(class_id)
        if cls is None:
            return None, "Class not found"
        if student_id not in cls["student_ids"]:
            return None, "Student not in class"
        cls["student_ids"].remove(student_id)
        return cls, None

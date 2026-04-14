"""
In-memory sample data for the ejb_test_py demo app.

Facilities represent school buildings.  Rooms belong to a facility.
"""

FACILITIES = [
    {"id": 1, "name": "Lincoln Elementary",    "address": "100 Oak St",   "city": "Springfield", "state": "IL"},
    {"id": 2, "name": "Westview Middle School", "address": "250 Maple Ave", "city": "Shelbyville", "state": "IL"},
    {"id": 3, "name": "Riverside High School",  "address": "500 River Rd", "city": "Capital City", "state": "IL"},
]

ROOMS = [
    # Lincoln Elementary
    {"id": 1,  "facility_id": 1, "name": "Room 101",     "capacity": 30},
    {"id": 2,  "facility_id": 1, "name": "Room 102",     "capacity": 28},
    {"id": 3,  "facility_id": 1, "name": "Library",      "capacity": 50},
    # Westview Middle School
    {"id": 4,  "facility_id": 2, "name": "Room 201",     "capacity": 32},
    {"id": 5,  "facility_id": 2, "name": "Computer Lab", "capacity": 24},
    {"id": 6,  "facility_id": 2, "name": "Auditorium",   "capacity": 200},
    # Riverside High School
    {"id": 7,  "facility_id": 3, "name": "Room 301",     "capacity": 35},
    {"id": 8,  "facility_id": 3, "name": "Science Lab",  "capacity": 28},
    {"id": 9,  "facility_id": 3, "name": "Media Room",   "capacity": 40},
]


def get_facility(facility_id: int):
    return next((f for f in FACILITIES if f["id"] == facility_id), None)


def get_rooms_for_facility(facility_id: int):
    return [r for r in ROOMS if r["facility_id"] == facility_id]

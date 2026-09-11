"""
What intake answers a granted ``POST /api/authorize`` with, for both of this
suite's stand-ins for intake: ``StubIntake`` in ``test_authenticate_status.py``
and ``MeshTestCase``'s ``FakeAuthorizeResponse`` in ``support.py``.

The field names are intake's. ``IntakeWeb.AuthorizationController.create/2``
renders ``:show, accesses: [access_map]`` with status 201, and
``IntakeWeb.AuthorizationJSON.show/1`` puts that list under ``data`` --
``accesses`` is the name of the render assign, never a key on the wire. Each
entry carries exactly four keys, and ``deprecation`` is added only when the
called version is deprecated. The values are stand-ins.

Both doubles answered ``{}`` until sc-483. ``test_intake_doubles.py`` checks them
against intake's keys, transcribed there rather than imported from here, so this
body cannot drift and still pass.
"""

from __future__ import annotations

from typing import Any, Dict


def granted() -> Dict[str, Any]:
    return {
        "authorized": True,
        "data": [
            {
                "id": "intake-double-access",
                "source_application_environment_id": "intake-double-source-app-env",
                "target_application_environment_id": "intake-double-target-app-env",
                "inserted_at": "2026-01-01T00:00:00Z",
            }
        ],
    }

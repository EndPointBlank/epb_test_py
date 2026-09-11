"""
The suite's two stand-ins for intake grant an authorize the way intake does.

A double written from the same misunderstanding as the code hides that
misunderstanding completely. The Elixir SDK read ``accesses`` from intake's 201
for its whole life because its own stubs answered ``accesses`` (sc-463). The JS,
Python and Java SDKs read nothing from the grant at all (sc-473). Both doubles
here answered a granted authorize with ``{}`` (sc-483), which agrees with any
reading of it, right or wrong.

The keys below are copied from intake, not from either double, so the doubles
cannot agree with each other and still be wrong.
``IntakeWeb.AuthorizationController.create/2`` renders a grant through
``IntakeWeb.AuthorizationJSON.show/1`` (intake
``lib/intake_web/controllers/authorization_json.ex``): the grant list sits under
``data``, one entry with exactly these four keys, and intake's
``authorization_controller_test.exs`` ("POST /api/authorize — authorized") pins
that list. ``deprecation`` is added only when the called version is deprecated,
so a default grant has none.

Neither double reaches the SDK's reading of the grant today. ``MeshTestCase``
replaces ``EndpointAuthorize.authorize`` whole, and every 201 ``StubIntake``
serves in ``test_authenticate_status.py`` answers ``/whoami``, which goes through
``authenticated`` and does not read the body. So these assertions are about the
bytes an SDK would be handed, not about what any SDK version makes of them.
"""

from __future__ import annotations

import json
from datetime import datetime

import requests
from django.test import SimpleTestCase

import end_point_blank as epb
from tests.support import MeshTestCase
from tests.test_authenticate_status import StubIntake

TOP_LEVEL_KEYS = ["authorized", "data"]
GRANT_KEYS = [
    "id",
    "inserted_at",
    "source_application_environment_id",
    "target_application_environment_id",
]


class _IntakeGrant:
    def assertIntakeGrant(self, body) -> None:  # noqa: N802 - unittest's naming
        self.assertEqual(sorted(body), TOP_LEVEL_KEYS)
        self.assertIs(body["authorized"], True)
        self.assertIsInstance(body["data"], list)
        self.assertEqual(len(body["data"]), 1, "intake renders the one access that granted the call")

        (grant,) = body["data"]
        self.assertEqual(sorted(grant), GRANT_KEYS)
        self.assertIsInstance(grant["source_application_environment_id"], str)
        self.assertTrue(grant["source_application_environment_id"])
        datetime.fromisoformat(grant["inserted_at"])


class MeshSuiteGrantTest(_IntakeGrant, MeshTestCase):
    def test_the_mesh_suite_is_granted_in_intakes_shape(self):
        granted = self.authorize.return_value

        self.assertEqual(granted.status_code, 201)
        self.assertIntakeGrant(granted.json())
        self.assertEqual(json.loads(granted.text), granted.json())


class StubIntakeGrantTest(_IntakeGrant, SimpleTestCase):
    def test_the_stub_intake_grants_in_intakes_shape(self):
        # Over its real socket, so this is the body a request would receive.
        with StubIntake():
            response = requests.post(
                f"{epb.Configuration().base_url}/api/authorize", json={}, timeout=5
            )

        self.assertEqual(response.status_code, 201)
        self.assertIntakeGrant(response.json())

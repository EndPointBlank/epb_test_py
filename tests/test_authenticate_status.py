"""
What the caller is told when intake refuses an ``@authenticated`` route.

This module exists because of a hole rather than a feature. No route in this
application -- and none in any of the five epb_test_* applications -- sat
behind ``@authenticated``; every protected route used ``@authorized``. That is
how the authenticate path in the JS and Java SDKs dropped intake's refusal
status for two releases without a test going red (sc-307): the two guards are
two transcriptions of one decision, only one of them carried the status, and
the only programs that would have shown the difference never called the other.
A pass/fail count over these applications cannot see a code path nothing calls.

This SDK is the one that got it right. ``authenticated`` and ``authorized``
share ``_route_path(request)`` and share ``refusal_from``, so the endpoint path
and the refusal status agree by construction rather than by two people
remembering. These tests are here to keep that true, and to make the third
member of the cross-SDK conformance set an actual measurement instead of an
assumption.

Nothing in the SDK is stubbed. ``StubIntake`` puts a real HTTP server on
loopback and points the SDK at it, so the status travels the whole real
distance -- socket, ``_http.post``, ``BasicAuthenticate``, the decorator,
``refusal_from``, ``JsonErrorMiddleware`` -- exactly as it would in production.
``tests/support.py`` doubles the SDK's command objects instead, which is right
for the mesh suite but would replace the very layer that reads intake's status,
so a bug that loses it between the socket and the caller is invisible that way.
That is the bug that stayed invisible.

The contract, from the SDK's own ``refusal_from``:

===========================  ==========================================
intake answered 401          caller sees 401  (re-check the credential)
intake answered 403          caller sees 403  (ask for a grant)
intake answered any non-201  caller sees that status, verbatim
intake did not answer        caller sees 503  (nothing judged this caller)
===========================  ==========================================
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from django.test import SimpleTestCase

import end_point_blank as epb


class StubIntake:
    """A real intake, on loopback, for the length of one test."""

    def __init__(self, status: int = 201, body: str = "{}") -> None:
        self.status = status
        self.body = body
        self.calls: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = {}
                stub.calls.append(
                    {
                        "url": self.path,
                        # What the SDK told intake about the request it is
                        # judging. `path` is the assertion that catches a guard
                        # resolving the endpoint differently from the other one.
                        "path": parsed.get("path"),
                        # BOTH keys, deliberately. intake reads `http_method`;
                        # `action` is the spelling the ports carried until
                        # sc-320 and is refused with :invalid_params. Recording
                        # only `action` -- which this stub did until
                        # 2026-09-10 -- let the double and the assertion agree
                        # with each other about a key intake never reads, which
                        # is exactly how a key-shape bug survives an in-process
                        # double.
                        "http_method": parsed.get("http_method"),
                        "action": parsed.get("action"),
                        "client_auth": parsed.get("client_auth"),
                    }
                )
                payload = stub.body.encode("utf-8")
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass  # keep the test output readable

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "StubIntake":
        self._thread.start()
        host, port = self._server.server_address
        self._previous_base_url = epb.Configuration().base_url
        epb.Configuration().base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, *exc) -> None:
        epb.Configuration().base_url = self._previous_base_url
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def answer_with(self, status: int, body: str = "{}") -> None:
        self.status = status
        self.body = body


class UnreachableIntake:
    """Point the SDK at a port with nothing behind it.

    Bind a port, read it back, then release it: nothing is listening, so the
    connection is refused rather than answered by whatever happens to be up.
    This is the "intake did not answer at all" case -- the one where nothing
    judged the caller, and 401 would blame a credential no one looked at.
    """

    def __enter__(self) -> "UnreachableIntake":
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self._previous_base_url = epb.Configuration().base_url
        epb.Configuration().base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, *exc) -> None:
        epb.Configuration().base_url = self._previous_base_url


class AuthenticateStatusTest(SimpleTestCase):
    """The status the client receives, over a real socket to a stub intake."""

    def setUp(self) -> None:
        super().setUp()
        # The three writers are fire-and-forget POSTs to `log_base_url`, which
        # the stub does not serve and which would otherwise retry against
        # whatever is on :4001.
        for target in (
            "end_point_blank.writers.request_writer.RequestWriter.write",
            "end_point_blank.writers.response_writer.ResponseWriter.write",
            "end_point_blank.writers.exception_writer.ExceptionWriter.write",
        ):
            mock.patch(target).start()
        self.addCleanup(mock.patch.stopall)

    _credential = 0

    def call(self, path: str):
        """A fresh credential per call, so no cached decision can answer."""
        type(self)._credential += 1
        return self.client.get(
            path, headers={"Authorization": f"Basic caller-{self._credential}"}
        )

    # -- the route exists and goes through the authenticate path -------------

    def test_whoami_is_served_when_intake_accepts_the_credential(self):
        with StubIntake(201) as intake:
            response = self.call("/whoami")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authenticated"], True)
        self.assertEqual(response.json()["application"], "ejb-test-py")
        self.assertEqual(len(intake.calls), 1, "intake must actually be consulted")

    def test_whoami_really_does_go_through_the_authenticate_path(self):
        with StubIntake(201) as intake:
            self.call("/whoami")

        only = intake.calls[0]
        self.assertEqual(only["url"], "/api/authorize")
        # `http_method`, not `action`. intake's AuthorizeAccess.authorize/1
        # matches on http_method and has no clause for action, so a payload
        # carrying the latter falls through to {:error, :invalid_params} and is
        # refused whatever credential it presents (sc-320). This assertion read
        # `action` until 2026-09-10 and therefore pinned the bug: it passed
        # against an SDK intake could never authenticate.
        self.assertEqual(only["http_method"], "GET")
        self.assertIsNone(
            only.get("action"),
            "the wire key is `http_method`; `action` means something else on "
            "intake's registration endpoints and must not reappear here",
        )
        self.assertTrue(only["client_auth"].startswith("Basic caller-"))

    # -- the contract: intake's own status, not a blanket 401 ----------------

    def test_a_403_reaches_the_caller_as_403(self):
        with StubIntake(403, '{"error":"access_denied"}'):
            response = self.call("/whoami")

        self.assertEqual(
            response.status_code,
            403,
            "403 means ask for a grant, 401 means re-check the credential; "
            "collapsing them sends integrators to debug the wrong thing",
        )
        self.assertIn("Authentication failed", response.json()["error"])
        self.assertIn("access_denied", response.json()["error"])

    def test_a_401_still_reaches_the_caller_as_401(self):
        with StubIntake(401, '{"error":"invalid_credentials"}'):
            response = self.call("/whoami")

        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid_credentials", response.json()["error"])

    def test_an_unreachable_intake_reaches_the_caller_as_503(self):
        with UnreachableIntake():
            response = self.call("/whoami")

        self.assertEqual(
            response.status_code,
            503,
            "nothing judged this caller, so 401 would blame a credential "
            "no one looked at",
        )

    def test_any_other_status_is_passed_through_verbatim(self):
        for status in (400, 429, 500, 502):
            with self.subTest(status=status):
                with StubIntake(status, '{"error":"whatever intake said"}'):
                    response = self.call("/whoami")
                self.assertEqual(response.status_code, status)

    # -- parity: the two guards must answer one refusal the same way ---------

    def test_both_guards_give_the_caller_the_same_status(self):
        # The regression test proper. One intake, one answer, two routes:
        # /whoami through `authenticated`, /schools through `authorized`.
        # Both short-circuit before any database work, so this needs no
        # Postgres even though /schools would otherwise read one.
        for status in (401, 403, 429):
            with self.subTest(status=status):
                with StubIntake(status, '{"error":"access_denied"}'):
                    via_authenticate = self.call("/whoami")
                    via_authorize = self.call("/schools")

                self.assertEqual(via_authenticate.status_code, status)
                self.assertEqual(via_authorize.status_code, status)
                self.assertEqual(
                    via_authenticate.status_code,
                    via_authorize.status_code,
                    f"the two guards disagree about a {status} from intake",
                )

    def test_both_guards_answer_503_when_intake_cannot_be_reached(self):
        with UnreachableIntake():
            via_authenticate = self.call("/whoami")
            via_authorize = self.call("/schools")

        self.assertEqual(via_authenticate.status_code, 503)
        self.assertEqual(via_authorize.status_code, 503)

    # -- the endpoint path the guard reports ---------------------------------

    def test_the_path_sent_to_intake_for_whoami_is_whoami(self):
        # Both decorators build the path with the same `_route_path(request)`,
        # so this holds for a route with variables too -- which is not true of
        # the JS and Java SDKs, where the authenticate path still resolves the
        # endpoint differently from the authorize path. Registration and
        # authorization must produce byte-identical paths or intake answers
        # `missing_target_endpoint`.
        with StubIntake(201) as intake:
            self.call("/whoami")

        self.assertEqual(intake.calls[0]["path"], "/whoami")

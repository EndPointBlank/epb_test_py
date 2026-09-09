"""
Shared scaffolding for the hop-budget tests (sc-264).

The contract's definition of done requires the suite to run "with no staging,
no AWS, no mesh and no app_portal". Two things in this application reach the
network on their own, so both are doubled here rather than left to whatever
happens to be listening on localhost:

* ``@authorized`` calls intake to decide the request. The decorator itself is
  NOT stubbed -- exercising it is the point of putting the mesh endpoints
  behind it -- only intake's answer is.
* ``ReportInteractionMiddleware`` writes request/response/exception records.
  The middleware stays in the chain (it is what primes ``request.body`` before
  a view reads it), only its writers are silenced.

``_http.post`` is then booby-trapped: if anything else in the SDK tries to make
an HTTP call during the suite, the test fails loudly instead of quietly
depending on a developer's local intake being up.
"""

from __future__ import annotations

import json
from unittest import mock

from django.test import SimpleTestCase

import mesh


class FakeAuthorizeResponse:
    """What ``EndpointAuthorize.authorize`` hands back: something with a status."""

    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self) -> dict:
        return self._body


class FakeDownstreamResponse:
    """The shape ``MeshCaller.post`` promises: ``status_code`` and ``text``."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class RecordingCaller(mesh.MeshCaller):
    """A stand-in for the next node that records every call it is handed.

    ``responder`` receives ``(target_url, headers, body)`` and returns the
    response to answer with; the default answers a terminated relay body, so a
    test that only cares about how many calls were made does not have to build
    one.
    """

    def __init__(self, responder=None) -> None:
        self.calls: list[dict] = []
        self._responder = responder or self._default_response

    def authorization_header(self, target_url: str) -> str:
        return "Bearer stub-access-token"

    def post(self, target_url, headers, body):
        self.calls.append({"url": target_url, "headers": dict(headers), "body": body})
        return self._responder(target_url, headers, body)

    @staticmethod
    def _default_response(target_url, headers, body):
        return FakeDownstreamResponse(
            200,
            json.dumps(
                {
                    "app": "epb_test_stub",
                    "hops_received": 0,
                    "hops_forwarded": None,
                    "terminated": True,
                    "run": None,
                    "payload": None,
                    "downstream": None,
                }
            ),
        )


class ChainCaller(RecordingCaller):
    """A recording caller that feeds the call back into this same application.

    This is what makes "an entry request with budget N produces exactly N
    downstream calls" provable offline: every hop is a real trip through
    ``urls.py`` -> ``@authorized`` -> the view -> ``mesh.handle``, and the
    recorded call list is the count.

    ``failure`` (a ``FakeDownstreamResponse`` or an exception) is returned
    instead of re-entering once ``fail_after`` calls have been recorded, which
    is how a refusal deep in the chain is made to happen.
    """

    def __init__(self, client, fail_after=None, failure=None) -> None:
        super().__init__()
        self.client = client
        self.fail_after = fail_after
        self.failure = failure

    def post(self, target_url, headers, body):
        self.calls.append({"url": target_url, "headers": dict(headers), "body": body})

        if self.fail_after is not None and len(self.calls) > self.fail_after:
            if isinstance(self.failure, BaseException):
                raise self.failure
            return self.failure

        # Content-Type is carried by the test client's own argument; passing it
        # in `headers` as well makes Django raise about the duplicate.
        forwarded = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        response = self.client.post(
            "/mesh/relay",
            data=body,
            content_type="application/json",
            headers=forwarded,
        )
        return FakeDownstreamResponse(
            response.status_code, response.content.decode("utf-8")
        )


class MeshTestCase(SimpleTestCase):
    """Base case: intake doubled, SDK writers silenced, network booby-trapped."""

    def setUp(self) -> None:
        super().setUp()
        self.authorize = mock.patch(
            "end_point_blank.commands.endpoint_authorize.EndpointAuthorize.authorize",
            return_value=FakeAuthorizeResponse(201),
        ).start()
        for target in (
            "end_point_blank.writers.request_writer.RequestWriter.write",
            "end_point_blank.writers.response_writer.ResponseWriter.write",
            "end_point_blank.writers.exception_writer.ExceptionWriter.write",
        ):
            mock.patch(target).start()
        mock.patch(
            "end_point_blank.commands._http.post",
            side_effect=AssertionError(
                "the suite made a real HTTP call through the SDK; it must not "
                "need intake, staging or a mesh to run"
            ),
        ).start()
        self.addCleanup(mock.patch.stopall)

    def refuse_authorization(self) -> None:
        """Make intake answer 'no' to the next inbound request."""
        self.authorize.return_value = FakeAuthorizeResponse(
            403, {"error": "Endpoint not granted to this client"}
        )

    def install(self, caller) -> None:
        """Swap the outbound seam for *caller* for the duration of the test."""
        patcher = mock.patch.object(mesh, "CALLER", caller)
        patcher.start()
        self.addCleanup(patcher.stop)
        return caller

    def downstream_url(self, url="https://epb-test-rails.example.invalid"):
        """Point this application at a next node, without touching the shell."""
        patcher = mock.patch.dict(
            "os.environ", {"EPB_MESH_DOWNSTREAM_URL": url}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return url

    def no_downstream_url(self):
        patcher = mock.patch.dict("os.environ", {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        import os

        os.environ.pop("EPB_MESH_DOWNSTREAM_URL", None)

    def relay(self, hops=None, run=None, body=None, path="/mesh/relay"):
        headers = {}
        if hops is not None:
            headers["X-EPB-Test-Hops"] = hops
        if run is not None:
            headers["X-EPB-Test-Run"] = run
        kwargs = {"content_type": "application/json", "headers": headers}
        if body is not None:
            kwargs["data"] = body
        return self.client.post(path, **kwargs)


def depth(payload) -> int:
    """How many ``downstream`` bodies are nested inside *payload*."""
    count = 0
    while isinstance(payload, dict) and payload.get("downstream") is not None:
        count += 1
        payload = payload["downstream"]
    return count

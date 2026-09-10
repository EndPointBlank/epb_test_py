"""
POST /mesh/relay and POST /mesh/reports -- the hop-budget contract (sc-264).

Nothing here needs staging, AWS, app_portal, intake or a mesh: the next node is
this same application, re-entered through the one seam (``mesh.CALLER``) that a
real deployment points at the network.
"""

from __future__ import annotations

import json
from unittest import mock

import requests

import mesh
from tests.support import (
    ChainCaller,
    FakeDownstreamResponse,
    MeshTestCase,
    NamingChainCaller,
    RecordingCaller,
    depth,
)
from tests.test_hop_parsing import ZERO_CASES


class AuthorizationTest(MeshTestCase):
    """The endpoints sit behind the same EPB authorization as the demo routes.

    An unprotected relay would prove nothing -- exercising cross-organization
    authorization is the entire reason the mesh exists.
    """

    def test_relay_is_refused_when_authorization_is_refused(self):
        caller = self.install(RecordingCaller())
        self.downstream_url()
        self.refuse_authorization()

        response = self.relay(hops="3")

        # `refuse_authorization()` makes intake answer 403 -- access_denied,
        # meaning the credential is fine and no grant covers this endpoint.
        # This asserted 401 until the SDK stopped collapsing every refusal to
        # that status (sc-299): the assertion was pinning the bug rather than
        # the contract, and it read as correct because the two agreed.
        self.assertEqual(response.status_code, 403)
        self.assertIn("Authorization failed", response.json()["error"])
        self.assertEqual(caller.calls, [], "a refused request must call nobody")

    def test_reports_is_refused_when_authorization_is_refused(self):
        caller = self.install(RecordingCaller())
        self.downstream_url()
        self.refuse_authorization()

        response = self.relay(hops="3", path="/mesh/reports")

        # 403, for the same reason as above.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(caller.calls, [])

    def test_relay_consults_authorization_for_its_own_route(self):
        self.install(RecordingCaller())
        self.downstream_url()

        self.relay(hops="0")

        self.assertEqual(self.authorize.call_count, 1)
        _environ, path, _version = self.authorize.call_args.args
        self.assertEqual(path, "/mesh/relay")

    def test_reports_consults_authorization_for_its_own_route(self):
        self.install(RecordingCaller())

        self.relay(hops="0", path="/mesh/reports")

        _environ, path, _version = self.authorize.call_args.args
        self.assertEqual(path, "/mesh/reports")

    def test_only_post_is_accepted(self):
        self.assertEqual(self.client.get("/mesh/relay").status_code, 405)
        self.assertEqual(self.client.get("/mesh/reports").status_code, 405)


class TerminationTest(MeshTestCase):
    """Budget N, and exactly N downstream calls. Asserted, not observed."""

    def test_budget_n_produces_exactly_n_downstream_calls(self):
        for budget in (1, 2, 3, 4, 5):
            with self.subTest(budget=budget):
                caller = ChainCaller(self.client)
                with mock.patch.object(mesh, "CALLER", caller), mock.patch.dict(
                    "os.environ",
                    {"EPB_MESH_DOWNSTREAM_URL": "https://next.example.invalid"},
                ):
                    response = self.relay(hops=str(budget))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    len(caller.calls),
                    budget,
                    f"budget {budget} should make exactly {budget} calls",
                )

    def test_the_chain_nests_one_body_per_hop(self):
        caller = self.install(ChainCaller(self.client))
        self.downstream_url()

        body = self.relay(hops="4").json()

        self.assertEqual(len(caller.calls), 4)
        # Counting nesting depth proves the hop count without instrumenting
        # anything -- the chain is self-describing.
        self.assertEqual(depth(body), 4)

    def test_each_hop_decrements_the_budget_by_one(self):
        caller = self.install(ChainCaller(self.client))
        self.downstream_url()

        self.relay(hops="4")

        forwarded = [call["headers"]["X-EPB-Test-Hops"] for call in caller.calls]
        self.assertEqual(forwarded, ["3", "2", "1", "0"])

    def test_the_last_hop_terminates(self):
        self.install(ChainCaller(self.client))
        self.downstream_url()

        body = self.relay(hops="3").json()

        innermost = body
        while innermost["downstream"] is not None:
            self.assertFalse(innermost["terminated"])
            self.assertIsNotNone(innermost["hops_forwarded"])
            innermost = innermost["downstream"]

        self.assertTrue(innermost["terminated"])
        self.assertEqual(innermost["hops_received"], 0)
        self.assertIsNone(innermost["hops_forwarded"])
        self.assertIsNone(innermost["downstream"])

    def test_a_budget_over_the_clamp_forwards_sixty_three(self):
        caller = self.install(RecordingCaller())
        self.downstream_url()

        body = self.relay(hops="1000000").json()

        self.assertEqual(body["hops_received"], 64)
        self.assertEqual(body["hops_forwarded"], 63)
        self.assertEqual(len(caller.calls), 1)
        self.assertEqual(caller.calls[0]["headers"]["X-EPB-Test-Hops"], "63")

    def test_a_clamped_budget_still_terminates(self):
        caller = self.install(ChainCaller(self.client))
        self.downstream_url()

        # In the real ring each hop is its own process; here all 64 are stacked
        # inside one interpreter, which exhausts the default recursion limit at
        # around 38 of them. Raising the limit alone risks the C stack on some
        # CPython versions, so the chain runs on a thread with a stack big
        # enough to hold it. Both are artifacts of proving this offline, not of
        # the contract.
        response = self.assertNoStackOverflow(lambda: self.relay(hops="1000000"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(caller.calls), 64)
        self.assertEqual(depth(response.json()), 64)


class ExhaustedBudgetTest(MeshTestCase):
    """n <= 0: answer, and call nobody."""

    def test_every_zero_case_answers_without_calling_anyone(self):
        for label, raw in ZERO_CASES:
            with self.subTest(case=label, raw=raw):
                caller = RecordingCaller()
                with mock.patch.object(mesh, "CALLER", caller), mock.patch.dict(
                    "os.environ",
                    {"EPB_MESH_DOWNSTREAM_URL": "https://next.example.invalid"},
                ):
                    response = self.relay(hops=raw)

                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["hops_received"], 0)
                self.assertIsNone(body["hops_forwarded"])
                self.assertTrue(body["terminated"])
                self.assertIsNone(body["downstream"])
                self.assertEqual(
                    caller.calls, [], f"{label!r} must not originate a call"
                )

    def test_terminating_needs_no_downstream_configuration(self):
        caller = self.install(RecordingCaller())
        self.no_downstream_url()

        response = self.relay(hops="0")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["terminated"])
        self.assertEqual(caller.calls, [])


class MissingConfigurationTest(MeshTestCase):
    """A budget with nowhere to spend it is a 500, never a quiet stop.

    A silent stop would make a broken mesh look like a working one that simply
    terminated, and a load run against it would report clean numbers for
    traffic that never happened.
    """

    def test_budget_with_no_downstream_url_is_a_named_five_hundred(self):
        caller = self.install(RecordingCaller())
        self.no_downstream_url()

        response = self.relay(hops="3")

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"], "downstream_not_configured")
        self.assertEqual(body["hops_received"], 3)
        self.assertIn("EPB_MESH_DOWNSTREAM_URL", body["message"])
        self.assertEqual(caller.calls, [])

    def test_it_is_not_reported_as_a_termination(self):
        self.install(RecordingCaller())
        self.no_downstream_url()

        body = self.relay(hops="3").json()

        self.assertNotIn("terminated", body)

    def test_an_empty_downstream_url_counts_as_missing(self):
        self.install(RecordingCaller())
        self.downstream_url("   ")

        response = self.relay(hops="1")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "downstream_not_configured")


class DownstreamFailureTest(MeshTestCase):
    """A refusal is never swallowed into a 200."""

    def test_non_200_becomes_502_preserving_the_status(self):
        caller = self.install(
            RecordingCaller(
                responder=lambda *_: FakeDownstreamResponse(
                    403, json.dumps({"error": "Authorization failed: not granted"})
                )
            )
        )
        self.downstream_url()

        response = self.relay(hops="3")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"], "downstream_failed")
        self.assertEqual(body["downstream_status"], 403)
        self.assertEqual(body["hops_received"], 3)
        self.assertIn("not granted", body["downstream_error"])
        self.assertEqual(len(caller.calls), 1)

    def test_a_five_hundred_downstream_is_also_502(self):
        self.install(
            RecordingCaller(
                responder=lambda *_: FakeDownstreamResponse(500, "boom")
            )
        )
        self.downstream_url()

        response = self.relay(hops="1")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["downstream_status"], 500)

    def test_a_connection_error_is_502_with_no_status(self):
        def explode(*_):
            raise requests.ConnectionError("Connection refused")

        self.install(RecordingCaller(responder=explode))
        self.downstream_url()

        response = self.relay(hops="2")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"], "downstream_failed")
        self.assertIsNone(body["downstream_status"])
        self.assertIn("Connection refused", body["downstream_error"])

    def test_a_timeout_is_502(self):
        def explode(*_):
            raise requests.Timeout("Read timed out")

        self.install(RecordingCaller(responder=explode))
        self.downstream_url()

        response = self.relay(hops="1")

        self.assertEqual(response.status_code, 502)
        self.assertIn("Read timed out", response.json()["downstream_error"])

    def test_a_two_hundred_that_is_not_json_is_502(self):
        self.install(
            RecordingCaller(
                responder=lambda *_: FakeDownstreamResponse(200, "<html>proxy</html>")
            )
        )
        self.downstream_url()

        response = self.relay(hops="1")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["downstream_status"], 200)

    def test_the_downstream_error_is_truncated_to_500_characters(self):
        self.install(
            RecordingCaller(
                responder=lambda *_: FakeDownstreamResponse(502, "x" * 5000)
            )
        )
        self.downstream_url()

        body = self.relay(hops="1").json()

        self.assertEqual(len(body["downstream_error"]), 500)

    def test_a_refusal_deep_in_the_chain_reaches_the_entry_point(self):
        # sc-265 counts refusals rather than dropping them, and the negative
        # control depends on one being visible from where the run started.
        caller = self.install(
            ChainCaller(
                self.client,
                fail_after=2,
                failure=FakeDownstreamResponse(403, '{"error":"not granted"}'),
            )
        )
        self.downstream_url()

        response = self.relay(hops="4")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"], "downstream_failed")
        self.assertEqual(len(caller.calls), 3)
        # Each node reports the status of ITS OWN downstream call, so an
        # intermediate hop's 502 is what the entry point sees. What matters is
        # that the failure is not swallowed into a 200 anywhere on the way back
        # -- the refused hop's own body is carried up inside downstream_error.
        self.assertEqual(body["downstream_status"], 502)
        self.assertIn("downstream_failed", body["downstream_error"])
        self.assertIn("403", body["downstream_error"])

    def test_a_failed_access_token_mint_is_502(self):
        class NoCredential(mesh.MeshCaller):
            def __init__(self):
                self.posted = []

            def post(self, *args):
                self.posted.append(args)
                raise AssertionError("must not post without a credential")

        caller = self.install(NoCredential())
        self.downstream_url()

        with mock.patch(
            "end_point_blank.tokens.access_tokens.AccessTokens.token",
            return_value=None,
        ):
            response = self.relay(hops="1")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"], "downstream_failed")
        self.assertIsNone(body["downstream_status"])
        self.assertEqual(caller.posted, [])


class WireFormatTest(MeshTestCase):
    def test_the_run_identifier_is_forwarded_verbatim(self):
        caller = self.install(ChainCaller(self.client))
        self.downstream_url()

        body = self.relay(hops="3", run="sc-265/run-17").json()

        self.assertEqual(body["run"], "sc-265/run-17")
        for call in caller.calls:
            self.assertEqual(call["headers"]["X-EPB-Test-Run"], "sc-265/run-17")
        self.assertEqual(body["downstream"]["run"], "sc-265/run-17")

    def test_an_absent_run_identifier_is_never_generated(self):
        caller = self.install(RecordingCaller())
        self.downstream_url()

        body = self.relay(hops="1").json()

        self.assertIsNone(body["run"])
        self.assertNotIn("X-EPB-Test-Run", caller.calls[0]["headers"])

    def test_the_payload_is_echoed_and_forwarded(self):
        caller = self.install(RecordingCaller())
        self.downstream_url()

        body = self.relay(hops="1", body=json.dumps({"payload": "abc"})).json()

        self.assertEqual(body["payload"], "abc")
        self.assertEqual(json.loads(caller.calls[0]["body"])["payload"], "abc")

    def test_an_empty_body_is_accepted(self):
        self.install(RecordingCaller())
        self.downstream_url()

        for label, body in (("no body", None), ("empty object", "{}")):
            with self.subTest(case=label):
                response = self.relay(hops="0", body=body)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["payload"])

    def test_the_app_field_names_this_repository(self):
        self.install(RecordingCaller())
        self.downstream_url()

        self.assertEqual(self.relay(hops="0").json()["app"], "epb_test_py")

    def test_the_app_field_can_be_overridden_for_a_deployment(self):
        self.install(RecordingCaller())
        with mock.patch.dict("os.environ", {"EPB_MESH_APP_NAME": "epb_test_py_west"}):
            self.assertEqual(self.relay(hops="0").json()["app"], "epb_test_py_west")

    def test_the_relay_path_is_appended_to_the_configured_base_url(self):
        caller = self.install(RecordingCaller())
        self.downstream_url("https://epb-test-rails.staging.example.invalid/")

        self.relay(hops="1")

        self.assertEqual(
            caller.calls[0]["url"],
            "https://epb-test-rails.staging.example.invalid/mesh/relay",
        )

    def test_reports_behaves_like_relay_except_that_it_keeps_its_own_path(self):
        caller = self.install(RecordingCaller())
        self.downstream_url()

        body = self.relay(hops="2", path="/mesh/reports").json()

        self.assertEqual(len(caller.calls), 1)
        self.assertEqual(body["hops_received"], 2)
        self.assertEqual(body["hops_forwarded"], 1)
        self.assertFalse(body["terminated"])
        self.assertIsNotNone(body["downstream"])
        # The budget, the body and the wire format are identical to relay's.
        # The path is not: it is preserved onto the next node. See
        # NegativeControlPathTest for why.
        self.assertTrue(caller.calls[0]["url"].endswith("/mesh/reports"))


class NegativeControlPathTest(MeshTestCase):
    """The path is preserved across hops, and the negative control is why.

    ``/mesh/reports`` is the ``reports`` API package, which sc-263 deliberately
    does NOT grant: a call to it must be refused. Forwarding it to the next
    node's ``/mesh/relay`` was the first decision, on the reasoning that a call
    refused at hop one never reaches a downstream path worth naming.

    That reasoning holds only while provisioning is correct -- and catching
    provisioning being wrong is the entire job of a negative control. If
    ``reports`` is wrongly granted at hop one, forwarding to ``/mesh/relay``
    turns a provisioning error into ordinary successful relay traffic and the
    load run reports clean numbers for a mesh that is misconfigured. Preserving
    the path keeps it failing at every hop. Loud beats clean-looking.
    """

    def test_reports_forwards_to_the_downstream_reports_path(self):
        caller = self.install(RecordingCaller())
        self.downstream_url("https://epb-test-rails.staging.example.invalid/")

        self.relay(hops="1", path="/mesh/reports")

        self.assertEqual(
            caller.calls[0]["url"],
            "https://epb-test-rails.staging.example.invalid/mesh/reports",
        )

    def test_reports_keeps_its_path_at_every_hop(self):
        caller = self.install(ChainCaller(self.client))
        self.downstream_url()

        response = self.relay(hops="3", path="/mesh/reports")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(caller.calls), 3)
        for call in caller.calls:
            self.assertTrue(
                call["url"].endswith("/mesh/reports"),
                f"{call['url']} stopped being the negative control",
            )
        # And every hop was authorized as reports, not as relay: the refusal
        # this endpoint exists to produce has to be asked for at each node.
        paths = [call.args[1] for call in self.authorize.call_args_list]
        self.assertEqual(paths, ["/mesh/reports"] * 4)

    def test_a_wrongly_granted_reports_call_keeps_failing_downstream(self):
        # The regression this rule exists for. Hop one wrongly grants reports
        # (the entry request succeeds); the rest of the ring is provisioned
        # correctly and refuses it. Forwarding to relay would have answered 200
        # here and the misprovisioning would never have been visible.
        def next_node(target_url, headers, body):
            if target_url.endswith("/mesh/reports"):
                return FakeDownstreamResponse(
                    403, json.dumps({"error": "Authorization failed: not granted"})
                )
            return RecordingCaller._default_response(target_url, headers, body)

        caller = self.install(RecordingCaller(responder=next_node))
        self.downstream_url()

        response = self.relay(hops="2", path="/mesh/reports")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"], "downstream_failed")
        self.assertEqual(body["downstream_status"], 403)
        self.assertIn("not granted", body["downstream_error"])
        self.assertTrue(caller.calls[0]["url"].endswith("/mesh/reports"))

    def test_relay_is_unaffected_and_never_forwards_to_reports(self):
        caller = self.install(ChainCaller(self.client))
        self.downstream_url()

        response = self.relay(hops="3")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(caller.calls), 3)
        for call in caller.calls:
            self.assertTrue(call["url"].endswith("/mesh/relay"))
        paths = [call.args[1] for call in self.authorize.call_args_list]
        self.assertEqual(paths, ["/mesh/relay"] * 4)


class OriginTest(MeshTestCase):
    """``origin``: who refused, recoverable at the entry point (sc-290).

    ``downstream_status`` is per-hop, so the originally refused status only
    rides up nested inside ``downstream_error`` -- and ``mesh.ERROR_LIMIT``
    truncates that nesting away at about four hops. ``origin`` is minted once,
    by the hop whose own downstream call failed, and forwarded verbatim by every
    hop above it.

    THE RULE MOST LIKELY TO BE GOT WRONG is the non-overwrite. A hop that
    replaces a received ``origin`` with its own still returns a well-formed
    response carrying a well-formed ``origin``; it just names the wrong
    application, and sc-265 would attribute every refusal in the ring to
    whichever node the load driver happened to enter at. There is no error to
    notice, so it is asserted directly and from several directions below.
    """

    REFUSAL = json.dumps({"error": "Authorization failed: not granted"})

    def refusing_caller(self, status=403, text=None):
        caller = self.install(
            RecordingCaller(
                responder=lambda *_: FakeDownstreamResponse(
                    status, self.REFUSAL if text is None else text
                )
            )
        )
        self.downstream_url()
        return caller

    # -- the observer mints it -------------------------------------------

    def test_the_hop_whose_downstream_failed_sets_origin(self):
        self.refusing_caller()

        body = self.relay(hops="3").json()

        self.assertEqual(
            body["origin"],
            {
                "app": "epb_test_py",
                "status": 403,
                "hops_received": 3,
                "error": "Authorization failed: not granted",
            },
        )

    def test_origin_names_the_observer_not_the_refuser(self):
        # The refuser's own name is not in the response it sent, and inventing
        # one would be a guess. The observing hop is the only participant that
        # knows both the status it received and its own identity.
        self.refusing_caller()
        with mock.patch.dict("os.environ", {"EPB_MESH_APP_NAME": "epb_test_py_west"}):
            body = self.relay(hops="2").json()

        self.assertEqual(body["origin"]["app"], "epb_test_py_west")

    def test_origin_hops_received_is_the_observers_own_budget(self):
        # So the entry point derives depth as entry_budget - origin.hops_received
        # without any hop having to know the entry budget.
        self.refusing_caller()

        self.assertEqual(self.relay(hops="5").json()["origin"]["hops_received"], 5)

    def test_a_clamped_budget_reports_the_clamped_value_in_origin(self):
        self.refusing_caller()

        body = self.relay(hops="1000000").json()

        self.assertEqual(body["hops_received"], 64)
        self.assertEqual(body["origin"]["hops_received"], 64)

    def test_a_non_json_two_hundred_keeps_its_status_in_origin(self):
        self.refusing_caller(status=200, text="<html>proxy</html>")

        body = self.relay(hops="1").json()

        self.assertEqual(body["origin"]["status"], 200)
        self.assertEqual(body["origin"]["app"], "epb_test_py")

    # -- the non-overwrite rule ------------------------------------------

    def deep_origin(self, **overrides):
        origin = {
            "app": "epb_test_rails",
            "status": 403,
            "hops_received": 1,
            "error": "access_denied",
        }
        origin.update(overrides)
        return origin

    def failure_body_carrying(self, origin):
        """What a hop below answers when the refusal happened below IT."""
        return json.dumps(
            {
                "app": "epb_test_js",
                "hops_received": 2,
                "error": "downstream_failed",
                "downstream_status": 502,
                "downstream_error": "...the nested walk, which truncates...",
                "origin": origin,
            }
        )

    def test_a_received_origin_is_forwarded_unchanged(self):
        origin = self.deep_origin()
        self.refusing_caller(status=502, text=self.failure_body_carrying(origin))

        body = self.relay(hops="4").json()

        self.assertEqual(body["origin"], origin)

    def test_a_hop_does_not_substitute_its_own_origin(self):
        # The failure mode this rule exists for, stated the other way round:
        # every field of the received object must survive, not just the object.
        self.refusing_caller(status=502, text=self.failure_body_carrying(self.deep_origin()))

        body = self.relay(hops="4").json()

        self.assertEqual(body["app"], "epb_test_py")
        self.assertNotEqual(body["origin"]["app"], body["app"])
        self.assertEqual(body["origin"]["status"], 403)
        self.assertNotEqual(body["origin"]["status"], body["downstream_status"])
        self.assertEqual(body["origin"]["hops_received"], 1)
        self.assertNotEqual(body["origin"]["hops_received"], body["hops_received"])
        self.assertEqual(body["origin"]["error"], "access_denied")

    def test_a_received_null_status_is_not_repaired(self):
        # A transport failure deeper down is a real answer to "who refused", and
        # `origin = received or mine` -- the obvious one-liner -- would keep it
        # only by accident. A null status must not tempt a hop into replacing
        # the object with its own, which has a status and would look better.
        origin = self.deep_origin(status=None, error="ConnectionError: refused")
        self.refusing_caller(status=502, text=self.failure_body_carrying(origin))

        body = self.relay(hops="3").json()

        self.assertEqual(body["origin"], origin)
        self.assertIsNone(body["origin"]["status"])
        self.assertEqual(body["downstream_status"], 502)

    def test_an_empty_received_origin_is_still_not_overwritten(self):
        # `exc.origin or {...}` passes every test above and fails this one: an
        # empty object is falsy, so the fallback fires and this hop's name is
        # published as the origin of a failure it did not observe.
        self.refusing_caller(status=502, text=self.failure_body_carrying({}))

        self.assertEqual(self.relay(hops="3").json()["origin"], {})

    def test_an_origin_that_is_not_an_object_is_ignored(self):
        # A node that answers `"origin": "epb_test_rails"` is not speaking this
        # contract, and forwarding a string would hand sc-265 something it
        # cannot read. This hop is the observer instead.
        self.refusing_caller(
            status=502, text=self.failure_body_carrying("epb_test_rails")
        )

        origin = self.relay(hops="3").json()["origin"]

        self.assertEqual(origin["app"], "epb_test_py")
        self.assertEqual(origin["status"], 502)

    def test_a_downstream_that_carries_no_origin_makes_this_hop_the_observer(self):
        # Every hop below this one predates sc-290, or the refusal came from the
        # authorization layer, which knows nothing about it.
        self.refusing_caller(status=502, text=json.dumps({"error": "downstream_failed"}))

        origin = self.relay(hops="3").json()["origin"]

        self.assertEqual(origin["app"], "epb_test_py")
        self.assertEqual(origin["status"], 502)

    # -- through a real chain --------------------------------------------

    def test_the_deepest_hop_owns_the_origin_through_a_real_chain(self):
        # Four hops, each answering under its own name, and the LAST one is the
        # one whose downstream refuses. Re-entering this same application is
        # what makes the chain provable with no mesh; the per-hop name is what
        # makes "the deep app, not an intermediate one" assertable at all.
        caller = self.install(
            NamingChainCaller(
                self.client,
                prefix="epb_test_py_hop",
                fail_after=3,
                failure=FakeDownstreamResponse(403, self.REFUSAL),
            )
        )
        self.downstream_url()

        with mock.patch.dict("os.environ", {"EPB_MESH_APP_NAME": "epb_test_py_hop0"}):
            response = self.relay(hops="4")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(len(caller.calls), 4)

        self.assertEqual(body["app"], "epb_test_py_hop0")
        self.assertEqual(body["origin"]["app"], "epb_test_py_hop3")
        self.assertEqual(body["origin"]["status"], 403)
        self.assertEqual(body["origin"]["hops_received"], 1)
        # Depth, derived at the entry point without any hop knowing the entry
        # budget: 4 - 1 == three hops down.
        self.assertEqual(4 - body["origin"]["hops_received"], 3)

    def test_downstream_status_stays_per_hop_while_origin_names_the_far_end(self):
        # origin does not replace downstream_status; both meanings coexist. The
        # entry point sees a 502 next door AND a 403 three hops away, and a 403
        # next door stays distinguishable from one far away.
        self.install(
            NamingChainCaller(
                self.client,
                prefix="epb_test_py_hop",
                fail_after=3,
                failure=FakeDownstreamResponse(403, self.REFUSAL),
            )
        )
        self.downstream_url()

        body = self.relay(hops="4").json()

        self.assertEqual(body["downstream_status"], 502)
        self.assertEqual(body["origin"]["status"], 403)
        # And at this depth the walk origin replaced has already stopped
        # working: 500 characters of nested envelope, cut mid-string.
        self.assertEqual(len(body["downstream_error"]), mesh.ERROR_LIMIT)
        with self.assertRaises(ValueError):
            json.loads(body["downstream_error"])

    def test_the_hop_next_door_agrees_about_the_origin(self):
        # Two hops, shallow enough that the nested body still parses -- so the
        # forwarded object can be compared with the one the observer minted.
        self.install(
            NamingChainCaller(
                self.client,
                prefix="epb_test_py_hop",
                fail_after=1,
                failure=FakeDownstreamResponse(403, self.REFUSAL),
            )
        )
        self.downstream_url()

        body = self.relay(hops="2").json()

        neighbour = json.loads(body["downstream_error"])
        self.assertEqual(neighbour["app"], "epb_test_py_hop1")
        self.assertEqual(neighbour["downstream_status"], 403)
        self.assertEqual(neighbour["origin"], body["origin"])
        self.assertEqual(body["origin"]["app"], "epb_test_py_hop1")

    def test_origin_survives_a_chain_the_nested_walk_does_not(self):
        # THE MEASUREMENT THIS FIELD EXISTS FOR. 64 hops (the clamp), refused at
        # the deepest one. The nested downstream_error is re-truncated to 500
        # characters at every level, so the refusal is unrecoverable from it;
        # origin is at the top of the entry response either way.
        #
        # 64 hops stacked inside one interpreter needs far more frames than the
        # default recursion limit, hence the deep-stack thread. Both are
        # artifacts of proving this offline, not of the contract.
        marker = "REFUSED-BY-THE-FAR-SIDE"
        caller = self.install(
            NamingChainCaller(
                self.client,
                prefix="epb_test_py_hop",
                fail_after=63,
                failure=FakeDownstreamResponse(
                    403, json.dumps({"error": f"access_denied {marker}"})
                ),
            )
        )
        self.downstream_url()

        response = self.assertNoStackOverflow(lambda: self.relay(hops="1000000"))

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(len(caller.calls), 64)

        self.assertEqual(body["origin"]["app"], "epb_test_py_hop63")
        self.assertEqual(body["origin"]["status"], 403)
        self.assertEqual(body["origin"]["hops_received"], 1)
        self.assertIn(marker, body["origin"]["error"])

        # And the walk this replaced: the far end is not in there at all.
        self.assertEqual(len(body["downstream_error"]), mesh.ERROR_LIMIT)
        self.assertNotIn(marker, body["downstream_error"])
        self.assertNotIn("403", body["downstream_error"])

    # -- failures that are not an HTTP status -----------------------------

    def test_a_transport_failure_has_a_null_origin_status(self):
        for label, error in (
            ("connection", requests.ConnectionError("Connection refused")),
            ("timeout", requests.Timeout("Read timed out")),
        ):
            with self.subTest(case=label):

                def explode(*_, _error=error):
                    raise _error

                self.install(RecordingCaller(responder=explode))
                self.downstream_url()

                body = self.relay(hops="2").json()

                self.assertEqual(body["origin"]["app"], "epb_test_py")
                self.assertIsNone(body["origin"]["status"])
                self.assertEqual(body["origin"]["hops_received"], 2)
                self.assertIn(str(error), body["origin"]["error"])

    def test_a_refusal_before_the_request_leaves_has_a_null_origin_status(self):
        # No token, so nothing was sent and there is no status to report -- but
        # it is still a refusal by the authorization layer, and sc-265 counts it.
        # The real seam is kept for authorization_header (RecordingCaller stubs
        # it, which would make the credential succeed and prove nothing).
        class NoCredential(mesh.MeshCaller):
            def post(self, *args):
                raise AssertionError("must not post without a credential")

        self.install(NoCredential())
        self.downstream_url()

        with mock.patch(
            "end_point_blank.tokens.access_tokens.AccessTokens.token",
            return_value=None,
        ):
            body = self.relay(hops="1").json()

        self.assertIsNone(body["origin"]["status"])
        self.assertEqual(body["origin"]["app"], "epb_test_py")
        self.assertIn("no access token", body["origin"]["error"])

    # -- the cap ----------------------------------------------------------

    def test_the_origin_error_is_capped_at_two_hundred_characters(self):
        self.refusing_caller(text=json.dumps({"error": "x" * 5000}))

        body = self.relay(hops="1").json()

        self.assertEqual(len(body["origin"]["error"]), mesh.ORIGIN_ERROR_LIMIT)
        self.assertEqual(mesh.ORIGIN_ERROR_LIMIT, 200)
        # And the per-hop field keeps its own, larger cap.
        self.assertEqual(len(body["downstream_error"]), mesh.ERROR_LIMIT)

    def test_a_long_non_json_reason_is_capped_too(self):
        self.refusing_caller(text="y" * 5000)

        self.assertEqual(
            len(self.relay(hops="1").json()["origin"]["error"]),
            mesh.ORIGIN_ERROR_LIMIT,
        )

    def test_the_origin_error_is_never_a_nested_envelope(self):
        # The truncation origin exists to fix must not reappear inside it: the
        # reason is the downstream's own error string, not its whole body.
        self.refusing_caller(
            status=502,
            text=json.dumps(
                {
                    "app": "epb_test_js",
                    "error": "downstream_failed",
                    "downstream_error": "z" * 400,
                }
            ),
        )

        error = self.relay(hops="1").json()["origin"]["error"]

        self.assertEqual(error, "downstream_failed")
        self.assertNotIn("z", error)

    # -- nothing else changed ---------------------------------------------

    def test_a_successful_chain_carries_no_origin(self):
        self.install(ChainCaller(self.client))
        self.downstream_url()

        body = self.relay(hops="3").json()

        self.assertEqual(depth(body), 3)
        while body is not None:
            self.assertNotIn("origin", body)
            body = body["downstream"]

    def test_a_terminated_request_carries_no_origin(self):
        self.install(RecordingCaller())
        self.downstream_url()

        body = self.relay(hops="0").json()

        self.assertTrue(body["terminated"])
        self.assertNotIn("origin", body)

    def test_the_unconfigured_five_hundred_carries_no_origin(self):
        # Nothing was called, so nothing observed a refusal. The contract states
        # this body exactly -- app, hops_received, error, message -- and it must
        # stay exactly that, so it can never be misread as either an exhausted
        # budget or a refusal somewhere in the ring.
        self.install(RecordingCaller())
        self.no_downstream_url()

        response = self.relay(hops="3")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            set(response.json()),
            {"app", "hops_received", "error", "message"},
        )

    def test_the_failure_body_keeps_every_field_it_had(self):
        # origin adds a field and removes nothing.
        self.refusing_caller()

        self.assertEqual(
            set(self.relay(hops="3").json()),
            {
                "app",
                "hops_received",
                "error",
                "downstream_status",
                "downstream_error",
                "origin",
            },
        )


class CallerSeamTest(MeshTestCase):
    """The default seam presents an SDK-minted access token, not a raw header."""

    def test_the_authorization_header_is_an_sdk_access_token(self):
        with mock.patch(
            "end_point_blank.tokens.access_tokens.AccessTokens.token",
            return_value="minted-token",
        ) as token:
            header = mesh.MeshCaller().authorization_header("https://next/mesh/relay")

        self.assertEqual(header, "Bearer minted-token")
        token.assert_called_once_with("https://next/mesh/relay")

    def test_a_refused_credential_raises_a_downstream_failure(self):
        with mock.patch(
            "end_point_blank.tokens.access_tokens.AccessTokens.token",
            return_value=None,
        ):
            with self.assertRaises(mesh.DownstreamFailed):
                mesh.MeshCaller().authorization_header("https://next/mesh/relay")

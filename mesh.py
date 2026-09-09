"""
The hop budget: how a request into the test-application ring is guaranteed to
stop (sc-264).

The authoritative specification is
``end_point_blank_deploy/docs/superpowers/specs/2026-09-08-hop-budget-contract.md``.
If this file and that file disagree, this file is wrong.

sc-263 wires the five ``epb_test_*`` applications into a ring, each calling the
next. A ring with no terminating rule is an infinite loop, and a load generator
pointed at one measures how fast a cycle spins rather than how the system
performs. Every request therefore carries a budget: ``n <= 0`` answers and calls
nobody, ``n > 0`` makes exactly one downstream call carrying ``n - 1``. One
entry request with budget N touches N+1 applications, and load becomes a
function of entry rate and N alone.

WHY THIS LIVES HERE AND NOT IN THE SDK
--------------------------------------
This is harness behaviour. It must never be pushed down into
``end_point_blank_py``: the SDK has no business knowing it is in a load test,
and a header the product propagates in production is a different feature with a
different threat model and a different review.
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests
from django.http import JsonResponse

logger = logging.getLogger(__name__)

HOPS_HEADER = "X-EPB-Test-Hops"
RUN_HEADER = "X-EPB-Test-Run"

#: A budget above this is treated as this rather than rejected, so a typo
#: (``X-EPB-Test-Hops: 1000000``) is bounded without inventing a failure mode
#: the load driver has to handle. 64 is 12 full laps of a five-node ring.
MAX_HOPS = 64

#: The mesh call. ``/mesh/reports`` is the negative control and exists to be
#: refused on the way in; what it forwards is still the mesh call.
RELAY_PATH = "/mesh/relay"

CONNECT_TIMEOUT = 3
READ_TIMEOUT = 10

#: The contract's cap on ``downstream_error``.
ERROR_LIMIT = 500

# ASCII whitespace, spelled out. ``str.strip()`` with no argument also eats
# U+00A0 and the rest of the Unicode space characters, and WSGI header values
# arrive latin-1-decoded, so a NBSP really can turn up in one. The contract says
# ASCII.
_ASCII_WHITESPACE = " \t\n\r\v\f"

# Deliberately not ``int()``. ``int(" 4 ")`` is 4, which is wanted, but
# ``int("+4")`` is 4, ``int("4_0")`` is 40 and ``int("٤")`` is 4 -- and the
# contract's table says all three are 0. The shape is checked before anything is
# converted, so the table wins over Python's defaults.
_DIGITS = re.compile(r"\A[0-9]+\Z")


class DownstreamNotConfigured(Exception):
    """A request still had budget, and there is nowhere to spend it."""


class DownstreamFailed(Exception):
    """The next node could not be reached, or refused, or answered rubbish."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def parse_hops(raw: str | None) -> int:
    """The budget carried by *raw*, per the contract's table.

    Absent, empty, whitespace-only, negative, zero and anything that is not a
    base-10 integer all answer 0. That default is the whole safety property: a
    missing header meaning "unlimited" is the one default that can run away, and
    it would run away inside a ring on a box that is simultaneously being
    measured.
    """
    if raw is None:
        return 0

    # PEP 3333 lets a WSGI server fold repeated headers into a single
    # comma-separated value, and waitress -- what this application runs under --
    # does. By the time Django hands over ``HTTP_X_EPB_TEST_HOPS`` the separate
    # headers are gone, so taking the part before the first comma is what "if
    # the header appears more than once, use the first value" has to mean here.
    first = raw.split(",", 1)[0].strip(_ASCII_WHITESPACE)

    if not _DIGITS.match(first):
        return 0

    return min(int(first), MAX_HOPS)


def app_name() -> str:
    """This application's name for the ``app`` field.

    Defaults to the repository name; ``EPB_MESH_APP_NAME`` overrides it for a
    deployment that needs to distinguish two instances of the same repository.
    """
    return os.environ.get("EPB_MESH_APP_NAME", "").strip() or "epb_test_py"


def downstream_base_url() -> str | None:
    """The next node in the ring, or ``None`` when nothing is wired.

    Read per request rather than captured at import, so a test can prove the
    unconfigured case without a standing environment and a container can be
    re-pointed without a rebuild.
    """
    return os.environ.get("EPB_MESH_DOWNSTREAM_URL", "").strip() or None


class MeshCaller:
    """The single seam between this application and the next node.

    sc-263 is rewriting the mesh from a two-organization layout to a
    five-organization ring, and with it the credential and grant each call
    presents. That change lands in :meth:`authorization_header` and nowhere
    else -- which is the point of there being one seam rather than a raw
    ``requests`` call inlined in the view.

    A test replaces the whole object (see ``mesh.CALLER``); nothing else in this
    module talks to the network.
    """

    def authorization_header(self, target_url: str) -> str:
        """The credential presented to the next node.

        Goes through the SDK's own client path -- an access token minted by
        intake for the URL about to be called -- rather than a hand-rolled
        header, because genuinely exercising cross-organization authorization is
        the entire reason the mesh exists. A raw HTTP client would bypass the
        one thing being tested.
        """
        from end_point_blank.tokens.access_tokens import AccessTokens

        token = AccessTokens().token(target_url)
        if not token:
            # The SDK has already logged why. Surfaced as a downstream failure
            # rather than swallowed: a call that never went out because this
            # application holds no usable credential is a refusal by the
            # authorization layer, and sc-265 counts refusals.
            raise DownstreamFailed(
                "EndPointBlank minted no access token for "
                f"{target_url}; the credential was refused or intake is unreachable"
            )
        return f"Bearer {token}"

    def post(self, target_url: str, headers: dict, body: str):
        """POST *body* to *target_url*. Returns anything with ``status_code``
        and ``text``; raises for a transport failure."""
        return requests.post(
            target_url,
            headers=headers,
            data=body,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )


#: Module-level so a test can swap it. Read through the module global at call
#: time -- never bound into another module with ``from mesh import CALLER``.
CALLER = MeshCaller()


def handle(request) -> JsonResponse:
    """Serve one mesh request. Shared by ``/mesh/relay`` and ``/mesh/reports``."""
    hops_received = parse_hops(request.headers.get(HOPS_HEADER))
    run = request.headers.get(RUN_HEADER)
    payload = _payload(request)

    if hops_received <= 0:
        return JsonResponse(
            {
                "app": app_name(),
                "hops_received": hops_received,
                "hops_forwarded": None,
                "terminated": True,
                "run": run,
                "payload": payload,
                "downstream": None,
            }
        )

    try:
        downstream = _forward(hops_received - 1, run, payload)
    except DownstreamNotConfigured as exc:
        # Loud, and distinguishable from a termination. A silent stop here would
        # make a broken mesh look like a working one that simply ran out of
        # budget, and a load run against it would report clean numbers for
        # traffic that never happened.
        logger.error("Mesh relay cannot continue: %s", exc)
        return JsonResponse(
            {
                "app": app_name(),
                "hops_received": hops_received,
                "error": "downstream_not_configured",
                "message": str(exc),
            },
            status=500,
        )
    except DownstreamFailed as exc:
        # Never swallowed into a 200: the negative control depends on a refusal
        # being visible from the entry point.
        logger.error(
            "Mesh relay downstream failed (status=%s): %s", exc.status, exc.message
        )
        return JsonResponse(
            {
                "app": app_name(),
                "hops_received": hops_received,
                "error": "downstream_failed",
                "downstream_status": exc.status,
                "downstream_error": exc.message[:ERROR_LIMIT],
            },
            status=502,
        )

    return JsonResponse(
        {
            "app": app_name(),
            "hops_received": hops_received,
            "hops_forwarded": hops_received - 1,
            "terminated": False,
            "run": run,
            "payload": payload,
            "downstream": downstream,
        }
    )


def _payload(request):
    """The opaque string to echo back, or ``None``.

    Same idiom as the demo CRUD views: an empty body is an empty document, and a
    body that is not JSON at all raises into ``JsonErrorMiddleware`` rather than
    being quietly treated as empty.
    """
    if not request.body:
        return None
    body = json.loads(request.body)
    if not isinstance(body, dict):
        return None
    return body.get("payload")


def _forward(hops: int, run: str | None, payload):
    """Make the one downstream call and return its body verbatim.

    :param hops: the already-decremented budget to hand on.
    """
    base = downstream_base_url()
    if base is None:
        raise DownstreamNotConfigured(
            "EPB_MESH_DOWNSTREAM_URL is not set, so this application cannot make "
            f"the downstream call the request still has budget for (forwarding {hops})"
        )

    target = base.rstrip("/") + RELAY_PATH

    headers = {"Content-Type": "application/json", HOPS_HEADER: str(hops)}
    if run is not None:
        # Verbatim, never modified, and never generated when it is absent.
        headers[RUN_HEADER] = run
    headers["Authorization"] = CALLER.authorization_header(target)

    body = json.dumps({} if payload is None else {"payload": payload})

    try:
        response = CALLER.post(target, headers, body)
    except DownstreamFailed:
        raise
    except Exception as exc:
        # Connection refused, DNS failure, timeout: no status to preserve.
        raise DownstreamFailed(f"{type(exc).__name__}: {exc}") from exc

    status = getattr(response, "status_code", None)
    text = getattr(response, "text", "") or ""

    if status != 200:
        raise DownstreamFailed(text, status=status)

    try:
        return json.loads(text)
    except ValueError as exc:
        # A 200 carrying something that is not a JSON document cannot be nested
        # verbatim, and pretending otherwise would break the chain's only
        # self-describing property. Usually a proxy answering for a node that is
        # not there.
        raise DownstreamFailed(
            f"downstream answered 200 with a body that is not JSON ({exc}): {text}",
            status=status,
        ) from exc

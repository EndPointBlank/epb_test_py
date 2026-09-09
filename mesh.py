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

WHO REFUSED, AS OPPOSED TO WHO ANSWERED
---------------------------------------
``downstream_status`` is per-hop by design, so a refusal deep in the ring
surfaces at the entry point as a 502 from the neighbour and the original status
only rides up nested inside ``downstream_error`` -- where :data:`ERROR_LIMIT`
truncates it away past about three hops. A failure response therefore also
carries an ``origin`` object, minted once by the hop that observed the failure
and forwarded verbatim by every hop above it (sc-290).

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

#: The two inbound mesh paths. THE PATH IS PRESERVED ACROSS HOPS: a request that
#: arrives on ``/mesh/relay`` forwards to the next node's ``/mesh/relay``, and
#: one that arrives on ``/mesh/reports`` forwards to the next node's
#: ``/mesh/reports``.
#:
#: ``/mesh/reports`` is the negative control -- an API package sc-263
#: deliberately does not grant -- and this was decided the other way first, on
#: the reasoning that a call refused at hop one never reaches a downstream path
#: worth naming. That holds only while provisioning is correct, and the negative
#: control exists precisely to catch provisioning being wrong. If ``reports`` is
#: wrongly granted at hop one, forwarding to ``/mesh/relay`` launders a
#: provisioning error into ordinary successful relay traffic and the run looks
#: clean; preserving the path keeps it failing, and loud, at every hop. Loud
#: beats clean-looking. Operator decision, 2026-09-08.
RELAY_PATH = "/mesh/relay"
REPORTS_PATH = "/mesh/reports"

CONNECT_TIMEOUT = 3
READ_TIMEOUT = 10

#: The contract's cap on ``downstream_error``. This is the truncation that made
#: ``origin`` necessary: ``downstream_status`` is per-hop, so the originally
#: refused status only rides up nested inside ``downstream_error`` -- and each
#: hop re-truncates that nesting to 500 characters against roughly 110
#: characters of envelope per level. Measured here on 2026-09-09: the original
#: status is still readable about three hops from the entry point and is gone at
#: four or more. In a five-node ring with budget 4 the refusals lost are exactly
#: the ones on the far side.
ERROR_LIMIT = 500

#: The contract's cap on ``origin.error``. Deliberately far below
#: :data:`ERROR_LIMIT` and never nested: the whole point of ``origin`` is to
#: survive the truncation above, and a reason that could itself carry a nested
#: envelope would re-create the problem inside the field that exists to fix it.
ORIGIN_ERROR_LIMIT = 200

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
    """The next node could not be reached, or refused, or answered rubbish.

    :param origin: the ``origin`` object the failing downstream body already
        carried, if it carried one. ``None`` means this application is the
        observer of the original failure and must mint the object itself -- see
        :func:`handle`.
    """

    def __init__(
        self,
        message: str,
        status: int | None = None,
        origin: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.origin = origin


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


def handle(request, path: str) -> JsonResponse:
    """Serve one mesh request. Shared by ``/mesh/relay`` and ``/mesh/reports``.

    :param path: the inbound mesh path, which is also the path this request
        forwards to. Required rather than defaulted, and stated by the caller
        rather than read off ``request.path``: a default would silently send a
        future endpoint's traffic to ``/mesh/relay`` -- the exact laundering
        this contract was amended to prevent -- and ``request.path`` carries
        whatever the WSGI layer reported, mount prefix and trailing slash
        included.
    """
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
        downstream = _forward(hops_received - 1, run, payload, path)
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
        #
        # SET ONCE, BY THE OBSERVER; FORWARDED VERBATIM BY EVERYONE ABOVE. If
        # the failing downstream body already carried an ``origin``, that one is
        # the deeper failure and this hop MUST NOT replace it with its own.
        # Overwriting here is the single most likely way to get this feature
        # wrong, and it fails silently: every response still has an ``origin``,
        # it just names the wrong application. sc-265 would then attribute every
        # refusal in the ring to whichever node it happened to enter at.
        origin = exc.origin
        if origin is None:
            origin = {
                # The observer, not the refuser: this application is the only
                # participant that reliably knows both the status it got back
                # and its own identity.
                "app": app_name(),
                # None for a transport failure, a timeout, or a refusal raised
                # before the request left.
                "status": exc.status,
                # The observer's OWN budget, which lets the entry point derive
                # depth as `entry_budget - origin.hops_received` without any hop
                # having to know the entry budget.
                "hops_received": hops_received,
                "error": _short_reason(exc.message),
            }

        logger.error(
            "Mesh relay downstream failed (status=%s, origin=%s status=%s): %s",
            exc.status,
            origin.get("app"),
            origin.get("status"),
            exc.message,
        )
        return JsonResponse(
            {
                "app": app_name(),
                "hops_received": hops_received,
                "error": "downstream_failed",
                # Unchanged, and still per-hop: the status of the node THIS
                # application called. A refusal next door stays distinguishable
                # from one far away. ``origin`` answers "who refused"; these two
                # answer "what did my own neighbour do".
                "downstream_status": exc.status,
                "downstream_error": exc.message[:ERROR_LIMIT],
                "origin": origin,
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


def _origin_in(text: str) -> dict | None:
    """The ``origin`` a downstream failure body already carries, or ``None``.

    Deeper is truer: whatever comes back here was minted by a hop closer to the
    original failure than this one, so it is forwarded byte for byte rather than
    re-derived. Anything that is not a JSON object with an object ``origin`` --
    a proxy's HTML, a plain 403 from the authorization layer, a node that
    predates this field -- answers ``None``, and this application becomes the
    observer instead.
    """
    try:
        body = json.loads(text)
    except (ValueError, TypeError):
        return None

    if not isinstance(body, dict):
        return None

    origin = body.get("origin")
    return origin if isinstance(origin, dict) else None


def _short_reason(message: str) -> str:
    """A bounded, non-nested reason for ``origin.error``.

    A failure body is usually ``{"error": "..."}`` -- the authorization layer's
    refusal, or a downstream node's own error name -- and that string is the
    reason worth keeping. Everything else falls back to the raw message. Either
    way it is cut to :data:`ORIGIN_ERROR_LIMIT`, because a field defined to
    survive truncation must not be able to be truncated into uselessness by the
    next hop.
    """
    try:
        body = json.loads(message)
    except (ValueError, TypeError):
        body = None

    if isinstance(body, dict):
        for key in ("error", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                message = value
                break

    return message[:ORIGIN_ERROR_LIMIT]


def _forward(hops: int, run: str | None, payload, path: str):
    """Make the one downstream call and return its body verbatim.

    :param hops: the already-decremented budget to hand on.
    :param path: the inbound path, preserved onto the next node.
    """
    base = downstream_base_url()
    if base is None:
        raise DownstreamNotConfigured(
            "EPB_MESH_DOWNSTREAM_URL is not set, so this application cannot make "
            f"the downstream call the request still has budget for (forwarding {hops})"
        )

    target = base.rstrip("/") + path

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
        # If the refusal happened deeper than the node just called, its body
        # carries the origin of it. Carried up untouched.
        raise DownstreamFailed(text, status=status, origin=_origin_in(text))

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

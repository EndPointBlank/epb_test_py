"""
Renders uncaught view exceptions as JSON 500 responses so the test app
never returns Django's HTML error page. EndPointBlank's UnauthorizedError
is already raised; if it has a status code attribute, surface it.
"""

import logging
import traceback

from django.http import JsonResponse

logger = logging.getLogger(__name__)


class JsonErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from end_point_blank.unauthorized_error import UnauthorizedError

        if isinstance(exception, UnauthorizedError):
            status = getattr(exception, "status_code", 401)
            return JsonResponse({"error": str(exception)}, status=status)

        logger.error("Unhandled exception: %s\n%s", exception, traceback.format_exc())
        return JsonResponse(
            {"error": f"{type(exception).__name__}: {exception}"},
            status=500,
        )

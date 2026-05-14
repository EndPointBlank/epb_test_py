import logging
import time

logger = logging.getLogger("access")


class AccessLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        ms = int((time.monotonic() - start) * 1000)
        logger.info('"%s %s" %d %dms', request.method, request.get_full_path(), response.status_code, ms)
        return response

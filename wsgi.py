import gc
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

# Allow more objects to accumulate before each GC cycle. The defaults
# (700, 10, 10) are tuned for interactive use; raising them reduces GC
# pause frequency at the cost of higher steady-state memory, which is the
# right trade-off for a long-running server with available headroom.
gc.set_threshold(10_000, 100, 100)

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

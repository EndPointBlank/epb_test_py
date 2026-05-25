import os

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "epb_app",
]

MIDDLEWARE = [
    "json_error_middleware.JsonErrorMiddleware",
    "end_point_blank.django.ReportInteractionMiddleware",
    "access_log.AccessLogMiddleware",
    "django.middleware.common.CommonMiddleware",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "access",
        },
    },
    "formatters": {
        "access": {
            "format": "[{asctime}] {message}",
            "style": "{",
            "datefmt": "%d/%b/%Y %H:%M:%S",
        },
    },
    "loggers": {
        "access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "end_point_blank": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 120,
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

ROOT_URLCONF = "urls"
WSGI_APPLICATION = "wsgi.application"

DATABASES = {}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

import os

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "epb_app",
]

MIDDLEWARE = [
    "end_point_blank.django.middleware.ReportInteractionMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "urls"
WSGI_APPLICATION = "wsgi.application"

DATABASES = {}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

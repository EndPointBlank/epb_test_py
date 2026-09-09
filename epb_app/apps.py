import os

from django.apps import AppConfig


class EpbAppConfig(AppConfig):
    name = "epb_app"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Both steps below need something outside this process: db.setup()
        # needs Postgres, register_django_endpoints() needs intake. The
        # hop-budget contract (sc-264) requires the test suite to run with
        # neither, so `manage.py test` sets EPB_SKIP_BOOTSTRAP before Django
        # starts and this hook stands down.
        #
        # Nothing is swallowed: outside a test run a failure here still takes
        # the boot down loudly, which is the point -- an application that
        # started without its tables or its endpoints registered is not a
        # working one.
        if os.environ.get("EPB_SKIP_BOOTSTRAP") == "1":
            return

        import db
        db.setup()

        from end_point_blank.django.endpoint_registrar import register_django_endpoints
        register_django_endpoints()

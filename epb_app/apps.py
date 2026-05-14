from django.apps import AppConfig


class EpbAppConfig(AppConfig):
    name = "epb_app"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import db
        db.setup()

        from end_point_blank.django.endpoint_registrar import register_django_endpoints
        register_django_endpoints()

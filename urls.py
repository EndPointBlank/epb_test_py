from django.urls import path
import views

urlpatterns = [
    path("status", views.status),
    path("whoami", views.whoami),
    path("schools", views.schools),
    path("schools/<int:school_id>", views.school),
    path("classes", views.classes),
    path("classes/<int:class_id>", views.single_class),
    path("classes/<int:class_id>/students", views.class_students),
    path("classes/<int:class_id>/students/<int:student_id>", views.class_student),
    path("errors", views.errors),
    path("mesh/relay", views.mesh_relay),
    path("mesh/reports", views.mesh_reports),
]

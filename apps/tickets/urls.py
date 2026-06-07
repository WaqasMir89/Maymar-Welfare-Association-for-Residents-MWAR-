from django.urls import path

from . import views

app_name = "complaints"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("export.csv", views.export_pending_complaints, name="export_pending"),
    path("new/", views.ticket_create, name="create"),
    path("<int:pk>/", views.ticket_detail, name="detail"),
    path("<int:pk>/status/", views.ticket_update_status, name="update_status"),
]

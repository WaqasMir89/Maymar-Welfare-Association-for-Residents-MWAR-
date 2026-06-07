from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("projects/", views.project_list, name="project_list"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("notices/", views.notice_list, name="notice_list"),
    path("notices/new/", views.notice_create, name="notice_create"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/<int:pk>/read/", views.notification_read, name="notification_read"),
    path("notifications/read-all/", views.notifications_read_all, name="notifications_read_all"),
    path("events/", views.event_list, name="event_list"),
    path("events/new/", views.event_create, name="event_create"),
    path("events/<int:pk>/", views.event_detail, name="event_detail"),
    path("gallery/", views.gallery, name="gallery"),
    path("gallery/upload/", views.gallery_upload, name="gallery_upload"),
    path("gallery/<int:pk>/delete/", views.gallery_delete, name="gallery_delete"),
    path("assets/", views.asset_list, name="asset_list"),
    path("assets/add/", views.asset_create, name="asset_create"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path("documents/<int:pk>/download/", views.document_download, name="document_download"),
]

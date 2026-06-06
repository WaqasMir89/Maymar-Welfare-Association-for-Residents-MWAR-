from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("projects/", views.project_list, name="project_list"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("notices/", views.notice_list, name="notice_list"),
    path("notices/new/", views.notice_create, name="notice_create"),
]

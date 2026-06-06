from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("transparency/", views.transparency, name="transparency"),
    path("contact/", views.contact, name="contact"),
    path("set-language/", views.set_language, name="set_language"),
]

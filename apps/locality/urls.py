from django.urls import path

from . import views

app_name = "locality"

urlpatterns = [
    path("registry/", views.property_list, name="property_list"),
]

from django.urls import path

from . import views

app_name = "dues"

urlpatterns = [
    path("staff/billing/", views.billing_board, name="billing_board"),
    path("staff/invoices/<int:pk>/pay/", views.record_payment, name="record_payment"),
    path("my-dues/", views.my_dues, name="my_dues"),
]

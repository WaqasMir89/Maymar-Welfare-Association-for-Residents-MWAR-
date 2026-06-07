from django.urls import path

from . import views

app_name = "dues"

urlpatterns = [
    path("staff/billing/", views.billing_board, name="billing_board"),
    path("staff/invoices/<int:pk>/pay/", views.record_payment, name="record_payment"),
    path("staff/donations/", views.donation_list, name="donation_list"),
    path("staff/donations/record/", views.record_donation_view, name="record_donation"),
    path("staff/expenses/", views.expense_list, name="expense_list"),
    path("staff/expenses/new/", views.expense_create, name="expense_create"),
    path("staff/expenses/<int:pk>/decide/", views.expense_decide, name="expense_decide"),
    path("receipts/dues/<int:pk>.pdf", views.dues_receipt_pdf, name="dues_receipt_pdf"),
    path("receipts/donation/<int:pk>.pdf", views.donation_receipt_pdf, name="donation_receipt_pdf"),
    path("my-dues/", views.my_dues, name="my_dues"),
]

from django.urls import path

from . import views

app_name = "members"

urlpatterns = [
    # Public application flow
    path("apply/", views.apply_start, name="apply_start"),
    path("apply/<int:pk>/documents/", views.apply_documents, name="apply_documents"),
    path("apply/<int:pk>/submit/", views.apply_submit, name="apply_submit"),
    path("apply/<int:pk>/success/", views.apply_success, name="apply_success"),
    # Member self-service
    path("dashboard/", views.dashboard, name="dashboard"),
    path("card/", views.my_card, name="my_card"),
    # Public verification + QR image
    path("verify/<uuid:qr_token>/", views.verify_card, name="verify_card"),
    path("card/<uuid:qr_token>/qr.png", views.card_qr, name="qr"),
    # Staff queue + review
    path("staff/queue/", views.application_queue, name="application_queue"),
    path("staff/applications/<int:pk>/", views.application_detail, name="application_detail"),
    path("staff/applications/<int:pk>/review/", views.application_review, name="application_review"),
]

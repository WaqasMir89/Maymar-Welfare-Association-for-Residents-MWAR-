"""Root URL configuration for the M.W.A.R Digital Platform."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core import views as core_views

# Password-reset flow — Django's built-in views with branded templates. The URL
# names are deliberately un-namespaced (`password_reset` etc.) because the
# built-in views and the reset email reverse them by those exact names.
password_reset_patterns = [
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/password_reset_email.html",
            subject_template_name="accounts/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
    path("staff/", core_views.staff_dashboard, name="staff_dashboard"),
    *password_reset_patterns,
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("locality/", include("apps.locality.urls")),
    path("members/", include("apps.members.urls")),
    path("dues/", include("apps.dues.urls")),
    path("complaints/", include("apps.tickets.urls")),
    path("content/", include("apps.content.urls")),
    path("api/v1/", include("config.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

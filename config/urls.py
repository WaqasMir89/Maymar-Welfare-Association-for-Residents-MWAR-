"""Root URL configuration for the M.W.A.R Digital Platform."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
    path("staff/", core_views.staff_dashboard, name="staff_dashboard"),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("locality/", include("apps.locality.urls")),
    path("members/", include("apps.members.urls")),
    path("dues/", include("apps.dues.urls")),
    path("complaints/", include("apps.tickets.urls")),
    path("content/", include("apps.content.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

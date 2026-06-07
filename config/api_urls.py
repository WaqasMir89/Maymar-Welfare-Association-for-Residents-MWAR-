"""REST API v1 (doc 04). Secondary surface to the server-rendered UI.

Mounted at ``/api/v1/``. JWT auth via simplejwt; OpenAPI at ``/api/v1/schema`` and
Swagger UI at ``/api/v1/docs``. This implements the core of the contract — auth,
locality, members (+ public card verify), dues/donations/expenses, tickets,
content, and the public read endpoints — with the standard envelope, RBAC
scoping, PII masking, and idempotent payments described in doc 04 §11.
"""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from apps.accounts.api import MeView, RegisterView
from apps.content.api import (
    EventViewSet,
    NoticeViewSet,
    NotificationViewSet,
    ProjectViewSet,
    PublicNewsView,
    PublicProjectsView,
    PublicReportsView,
)
from apps.dues.api import DonationViewSet, ExpenseViewSet, InvoiceViewSet
from apps.locality.api import PropertyViewSet, SectorViewSet
from apps.members.api import CardVerifyView, MemberViewSet
from apps.tickets.api import TicketViewSet

# Doc-04 paths carry no trailing slash (e.g. ``/api/v1/members``).
router = DefaultRouter(trailing_slash=False)
router.register("sectors", SectorViewSet, basename="api-sector")
router.register("properties", PropertyViewSet, basename="api-property")
router.register("members", MemberViewSet, basename="api-member")
router.register("dues/invoices", InvoiceViewSet, basename="api-invoice")
router.register("donations", DonationViewSet, basename="api-donation")
router.register("expenses", ExpenseViewSet, basename="api-expense")
router.register("tickets", TicketViewSet, basename="api-ticket")
router.register("projects", ProjectViewSet, basename="api-project")
router.register("events", EventViewSet, basename="api-event")
router.register("notices", NoticeViewSet, basename="api-notice")
router.register("notifications", NotificationViewSet, basename="api-notification")

auth_patterns = [
    path("register", RegisterView.as_view(), name="api-register"),
    path("login", TokenObtainPairView.as_view(), name="api-login"),
    path("refresh", TokenRefreshView.as_view(), name="api-refresh"),
    path("logout", TokenBlacklistView.as_view(), name="api-logout"),
    path("me", MeView.as_view(), name="api-me"),
]

public_patterns = [
    path("projects", PublicProjectsView.as_view(), name="api-public-projects"),
    path("news", PublicNewsView.as_view(), name="api-public-news"),
    path("reports", PublicReportsView.as_view(), name="api-public-reports"),
]

urlpatterns = [
    path("auth/", include(auth_patterns)),
    path("public/", include(public_patterns)),
    path("verify/card/<uuid:pk>", CardVerifyView.as_view({"get": "retrieve"}),
         name="api-verify-card"),
    path("schema", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("", include(router.urls)),
]

"""Content API: projects, events, notices + PUBLIC project/news/report endpoints."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Event, Notice, Notification, Project


class ProjectSerializer(serializers.ModelSerializer):
    budget = serializers.DecimalField(max_digits=12, decimal_places=2,
                                      coerce_to_string=True, allow_null=True)

    class Meta:
        model = Project
        fields = ["id", "title", "slug", "summary", "status", "budget",
                  "start_date", "end_date", "created_at"]
        read_only_fields = ["slug"]


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "description", "starts_at", "ends_at",
                  "location", "is_public", "rsvp_enabled"]


class NoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notice
        fields = ["id", "title", "body", "audience", "published_at"]


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    queryset = Project.objects.order_by("-created_at")
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer
    queryset = Event.objects.all()
    permission_classes = [IsAuthenticated]


class NoticeViewSet(viewsets.ModelViewSet):
    serializer_class = NoticeSerializer
    queryset = Notice.objects.order_by("-published_at")
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "url", "level", "is_read", "created_at"]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """The caller's own in-app notifications. ``?unread=true`` filters unread."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = self.request.user.notifications.all()
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        return qs

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)


# --------------------------------------------------------------- PUBLIC --
class PublicProjectsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=ProjectSerializer(many=True))
    def get(self, request):
        qs = Project.objects.exclude(status=Project.Status.PLANNED).order_by("-created_at")
        return Response(ProjectSerializer(qs, many=True).data)


class PublicNewsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=NoticeSerializer(many=True))
    def get(self, request):
        qs = Notice.objects.filter(audience=Notice.Audience.PUBLIC).order_by("-published_at")[:20]
        return Response(NoticeSerializer(qs, many=True).data)


class PublicReportsView(APIView):
    """PUBLIC financial transparency snapshot (same figures as the web page)."""

    permission_classes = [AllowAny]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        from apps.dues.reports import transparency_summary

        s = transparency_summary()
        return Response({
            "dues_collected": f'{s["dues_collected"]:.2f}',
            "donations_total": f'{s["donations_total"]:.2f}',
            "expenses_total": f'{s["expenses_total"]:.2f}',
            "balance": f'{s["balance"]:.2f}',
            "collection_rate": float(s["collection_rate"]),
            "currency": "PKR",
        })

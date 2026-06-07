"""Members API: role-scoped list, self, and PUBLIC card verification.

CNIC is masked by default; the full value is serialized only for callers holding
``members.view_pii`` and every such read is written to the audit log (doc 06).
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.models import AuditLog
from apps.core.services import record_audit

from .models import MemberCard, MemberProfile


class MemberSerializer(serializers.ModelSerializer):
    cnic = serializers.SerializerMethodField()
    membership_class = serializers.SerializerMethodField()
    property = serializers.SerializerMethodField()

    class Meta:
        model = MemberProfile
        fields = ["id", "member_number", "full_name", "father_or_husband_name",
                  "cnic", "phone", "status", "membership_class", "property", "join_date"]

    def get_cnic(self, obj) -> str:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.has_perm("members.view_pii"):
            return obj.cnic
        return obj.masked_cnic

    def get_membership_class(self, obj) -> str | None:
        m = obj.current_membership
        return m.get_membership_class_display() if m else None

    def get_property(self, obj) -> str | None:
        r = obj.current_residency
        return str(r.property) if r else None


class MemberViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["full_name", "member_number"]

    def get_queryset(self):
        qs = MemberProfile.objects.select_related("user").order_by("-created_at")
        from apps.accounts.permissions import is_staff_member

        user = self.request.user
        if not is_staff_member(user):
            # Members may only see their own profile through this surface.
            qs = qs.filter(user=user)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(full_name__icontains=search)
        return qs

    def _audit_pii(self, members):
        if self.request.user.has_perm("members.view_pii"):
            for m in members:
                record_audit(AuditLog.Action.PII_ACCESS, "MemberProfile", m.pk,
                             actor=self.request.user, metadata={"context": "api"})

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # Audit only the rows actually disclosed on the returned page.
        page = getattr(self.paginator, "page", None)
        self._audit_pii(list(page) if page is not None
                        else self.filter_queryset(self.get_queryset()))
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self._audit_pii([instance])
        return Response(self.get_serializer(instance).data)

    @extend_schema(responses=MemberSerializer)
    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def me(self, request):
        profile = getattr(request.user, "member_profile", None)
        if not profile:
            return Response({"detail": "No member profile."}, status=404)
        self._audit_pii([profile])
        return Response(self.get_serializer(profile).data)


class CardVerifyView(viewsets.ViewSet):
    """PUBLIC: validate a member card by QR token — minimal, non-sensitive data."""

    permission_classes = [AllowAny]

    @extend_schema(responses=inline_serializer("CardVerify", fields={
        "valid": serializers.BooleanField(),
        "member_number": serializers.CharField(),
        "full_name": serializers.CharField(),
        "status": serializers.CharField(),
    }))
    def retrieve(self, request, pk=None):
        card = MemberCard.objects.select_related("member").filter(qr_token=pk).first()
        valid = bool(
            card
            and card.status == MemberCard.Status.ACTIVE
            and card.member.status == MemberProfile.Status.ACTIVE
        )
        if not card:
            return Response({"valid": False}, status=404)
        return Response({
            "valid": valid,
            "member_number": card.member_number,
            "full_name": card.member.full_name,
            "status": card.member.get_status_display(),
        })

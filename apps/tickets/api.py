"""Tickets API: role-scoped list, create, and threaded messages.

Members see only their own tickets and never internal staff notes; staff see all.
"""

from __future__ import annotations

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Ticket, TicketMessage


def _staff(user):
    from apps.accounts.permissions import is_staff_member

    return is_staff_member(user)


class TicketMessageSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField()

    class Meta:
        model = TicketMessage
        fields = ["id", "author", "body", "is_internal", "created_at"]
        read_only_fields = ["author", "created_at"]


class TicketSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)
    assigned_to = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "ticket_number", "title", "description", "category",
                  "priority", "status", "created_by", "assigned_to", "created_at"]
        read_only_fields = ["ticket_number", "status", "created_by", "assigned_to"]


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Ticket.objects.select_related("created_by", "assigned_to").order_by("-created_at")
        user = self.request.user
        if not _staff(user) or self.request.query_params.get("mine") == "true":
            qs = qs.filter(created_by=user)
        for field in ("status", "category", "priority"):
            val = self.request.query_params.get(field)
            if val:
                qs = qs.filter(**{field: val})
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def update(self, request, *args, **kwargs):
        # Only staff may change status/assignment/priority.
        if not _staff(request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Only staff may update a ticket.")
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        ticket = self.get_object()
        is_staff = _staff(request.user)
        if request.method == "POST":
            body = (request.data.get("body") or "").strip()
            if not body:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"body": ["Message body is required."]})
            # Only staff may post internal notes.
            internal = bool(request.data.get("is_internal")) and is_staff
            msg = TicketMessage.objects.create(
                ticket=ticket, author=request.user, body=body, is_internal=internal
            )
            return Response(TicketMessageSerializer(msg).data, status=status.HTTP_201_CREATED)

        qs = ticket.messages.select_related("author").order_by("created_at")
        if not is_staff:
            qs = qs.filter(is_internal=False)
        return Response(TicketMessageSerializer(qs, many=True).data)

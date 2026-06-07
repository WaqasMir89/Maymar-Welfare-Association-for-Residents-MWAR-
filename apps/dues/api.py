"""Dues/donations/expenses API: role-scoped reads, idempotent payments."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Donation, DuesInvoice, DuesPlan, Expense
from .services import create_expense, decide_expense, record_donation, record_dues_payment


def _staff(user):
    from apps.accounts.permissions import is_staff_member

    return is_staff_member(user)


class DuesPlanSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)

    class Meta:
        model = DuesPlan
        fields = ["id", "name", "amount", "period", "applies_to", "active"]


class InvoiceSerializer(serializers.ModelSerializer):
    property = serializers.StringRelatedField()
    member = serializers.StringRelatedField()
    plan = serializers.StringRelatedField()
    amount_due = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)
    balance = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()

    class Meta:
        model = DuesInvoice
        fields = ["id", "property", "member", "plan", "period_start", "period_end",
                  "amount_due", "amount_paid", "balance", "currency", "due_date", "status"]

    def get_balance(self, obj) -> str:
        return f"{obj.balance:.2f}"

    def get_currency(self, obj) -> str:
        return "PKR"


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = DuesInvoice.objects.select_related("property", "member", "plan")
        user = self.request.user
        if not _staff(user):
            profile = getattr(user, "member_profile", None)
            qs = qs.filter(member=profile) if profile else qs.none()
        for field in ("status",):
            val = self.request.query_params.get(field)
            if val:
                qs = qs.filter(**{field: val})
        return qs.order_by("-period_start")

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def payments(self, request, pk=None):
        """Record a payment. Honours an ``Idempotency-Key`` request header."""
        if not request.user.has_perm("dues.record_payment"):
            raise PermissionDenied("Recording payments requires dues.record_payment.")
        invoice = self.get_object()
        try:
            amount = Decimal(str(request.data.get("amount")))
        except Exception:
            raise ValidationError({"amount": ["A valid decimal amount is required."]})
        if amount <= 0:
            raise ValidationError({"amount": ["Amount must be greater than zero."]})

        payment = record_dues_payment(
            invoice,
            amount=amount,
            method=request.data.get("method", "cash"),
            user=request.user,
            reference=request.data.get("reference", ""),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            {"receipt_number": payment.receipt_number,
             "amount": f"{payment.amount:.2f}", "currency": "PKR",
             "invoice": invoice.id, "status": invoice.status},
            status=status.HTTP_201_CREATED,
        )


class DonationSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)

    class Meta:
        model = Donation
        fields = ["id", "donor_name", "amount", "currency", "purpose", "method",
                  "reference", "receipt_number", "is_public", "donated_at"]
        read_only_fields = ["receipt_number", "donated_at"]


class DonationViewSet(viewsets.ModelViewSet):
    serializer_class = DonationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Donation.objects.order_by("-donated_at")

    def create(self, request, *args, **kwargs):
        if not request.user.has_perm("dues.record_payment"):
            raise PermissionDenied("Recording donations requires dues.record_payment.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        donation = record_donation(
            donor_name=data["donor_name"], amount=data["amount"], user=request.user,
            method=data.get("method", "cash"), purpose=data.get("purpose", ""),
            reference=data.get("reference", ""), is_public=data.get("is_public", False),
        )
        return Response(self.get_serializer(donation).data, status=status.HTTP_201_CREATED)


class ExpenseSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)

    class Meta:
        model = Expense
        fields = ["id", "category", "amount", "description", "incurred_on", "status"]
        read_only_fields = ["status"]


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = Expense.objects.order_by("-incurred_on")
        val = self.request.query_params.get("status")
        return qs.filter(status=val) if val else qs

    def create(self, request, *args, **kwargs):
        if not request.user.has_perm("dues.record_payment"):
            raise PermissionDenied("Logging expenses requires dues.record_payment.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        expense = create_expense(
            category=data["category"], amount=data["amount"], user=request.user,
            description=data.get("description", ""), incurred_on=data.get("incurred_on"),
        )
        return Response(self.get_serializer(expense).data, status=status.HTTP_201_CREATED)

    def _decide(self, request, approve):
        if not request.user.has_perm("dues.approve_expense"):
            raise PermissionDenied("Deciding expenses requires dues.approve_expense.")
        expense = decide_expense(self.get_object(), approve=approve, user=request.user)
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, approve=True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, approve=False)

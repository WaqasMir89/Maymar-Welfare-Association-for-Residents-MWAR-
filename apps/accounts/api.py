"""Auth API: registration + the `me` endpoint (login/refresh via simplejwt)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .permissions import role_names


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    member_profile_id = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "is_staff",
                  "roles", "permissions", "member_profile_id"]

    def get_roles(self, obj) -> list[str]:
        return role_names(obj)

    def get_member_profile_id(self, obj) -> int | None:
        profile = getattr(obj, "member_profile", None)
        return profile.id if profile else None

    def get_permissions(self, obj) -> list[str]:
        # Only the platform-relevant custom permissions, not the full Django set.
        wanted = {"members.view_pii", "members.approve_membership",
                  "members.review_application", "dues.record_payment",
                  "dues.approve_expense", "content.broadcast_notice"}
        return sorted(p for p in obj.get_all_permissions() if p in wanted)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["email", "full_name", "phone", "password"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @extend_schema(request=RegisterSerializer, responses=MeSerializer)
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(MeSerializer(user).data, status=status.HTTP_201_CREATED)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)

"""Create the role groups and wire their permissions (idempotent)."""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from apps.accounts.permissions import ROLE_PERMISSIONS


class Command(BaseCommand):
    help = "Create RBAC role groups and assign their permissions."

    def handle(self, *args, **options):
        for role, perms in ROLE_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=role)
            verb = "Created" if created else "Updated"

            if perms == ["__all__"]:
                group.permissions.set(Permission.objects.all())
                self.stdout.write(self.style.SUCCESS(f"{verb} {role} (all permissions)"))
                continue

            resolved = []
            for dotted in perms:
                app_label, codename = dotted.split(".")
                try:
                    resolved.append(
                        Permission.objects.get(
                            content_type__app_label=app_label, codename=codename
                        )
                    )
                except Permission.DoesNotExist:
                    self.stderr.write(self.style.WARNING(f"  missing permission: {dotted}"))
            group.permissions.set(resolved)
            self.stdout.write(self.style.SUCCESS(f"{verb} {role} ({len(resolved)} perms)"))

        self.stdout.write(self.style.SUCCESS("RBAC setup complete."))

from django.contrib import admin

from .models import Event, Notice, Project, ProjectUpdate


class UpdateInline(admin.StackedInline):
    model = ProjectUpdate
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "budget", "is_public")
    list_filter = ("status", "is_public")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [UpdateInline]


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "published_at", "via_sms")
    list_filter = ("audience",)


admin.site.register(Event)

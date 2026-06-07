from django.contrib import admin

from .models import Event, Notice, Project, ProjectUpdate, PublicDocument


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


@admin.register(PublicDocument)
class PublicDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "uploaded_by", "created_at")
    list_filter = ("category", "is_published")


admin.site.register(Event)

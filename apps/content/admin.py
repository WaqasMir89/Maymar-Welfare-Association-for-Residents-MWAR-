from django.contrib import admin

from .models import (
    Event,
    Notice,
    OrganizationGoal,
    OrganizationProfile,
    Project,
    ProjectUpdate,
    PublicDocument,
    RoadmapMilestone,
)


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


class GoalInline(admin.TabularInline):
    model = OrganizationGoal
    extra = 1


class MilestoneInline(admin.TabularInline):
    model = RoadmapMilestone
    extra = 1


@admin.register(OrganizationProfile)
class OrganizationProfileAdmin(admin.ModelAdmin):
    list_display = ("chairman_name", "chairman_title", "roadmap_year")
    inlines = [GoalInline, MilestoneInline]

    def has_add_permission(self, request):
        # Singleton — edit the one row rather than adding new ones.
        return not OrganizationProfile.objects.exists()


admin.site.register(Event)

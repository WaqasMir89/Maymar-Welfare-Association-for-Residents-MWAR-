from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketMessage


class MessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_number", "title", "category", "priority", "status", "assigned_to")
    list_filter = ("status", "category", "priority")
    search_fields = ("ticket_number", "title")
    inlines = [MessageInline]


admin.site.register(TicketAttachment)

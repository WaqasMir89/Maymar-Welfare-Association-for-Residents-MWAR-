from django import forms

from .models import Ticket, TicketMessage


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["title", "category", "priority", "property", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class TicketMessageForm(forms.ModelForm):
    class Meta:
        model = TicketMessage
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}

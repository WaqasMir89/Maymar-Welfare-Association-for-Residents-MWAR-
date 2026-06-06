"""Membership application forms (used for both self-service and assisted entry)."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.locality.models import Property

from .models import ApplicationDocument, MembershipApplication, ResidencyType, class_for_residency


class ApplicationForm(forms.ModelForm):
    declaration_accepted = forms.BooleanField(
        required=True,
        label=_(
            "I solemnly declare (حلفیہ اقرار) that the information above is correct "
            "and I will abide by the association's constitution."
        ),
    )

    class Meta:
        model = MembershipApplication
        fields = [
            "full_name", "father_or_husband_name", "cnic", "phone",
            "profession", "household_size", "property", "residency_type",
            "declaration_accepted",
        ]
        widgets = {
            "cnic": forms.TextInput(attrs={"placeholder": "42101-1234567-1"}),
            "phone": forms.TextInput(attrs={"placeholder": "0301-2345678"}),
            "residency_type": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.select_related(
            "sub_sector__sector"
        ).order_by("sub_sector", "house_number")
        for name, field in self.fields.items():
            if name not in ("declaration_accepted", "residency_type"):
                field.widget.attrs.setdefault("class", "input")

    def save(self, commit=True):
        application = super().save(commit=False)
        application.requested_class = class_for_residency(application.residency_type)
        if commit:
            application.save()
        return application


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = ApplicationDocument
        fields = ["doc_type", "file"]


class ReviewForm(forms.Form):
    DECISIONS = [
        ("approve", _("Approve")),
        ("docs_required", _("Request more documents")),
        ("reject", _("Reject")),
    ]
    decision = forms.ChoiceField(choices=DECISIONS, widget=forms.RadioSelect)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label=_("Notes"))

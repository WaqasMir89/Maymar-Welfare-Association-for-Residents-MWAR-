"""Auth forms: email-based login and member self-registration."""

from __future__ import annotations

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from apps.core.validators import phone_validator

from .models import User


class EmailLoginForm(forms.Form):
    email = forms.EmailField(label=_("Email"))
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        password = cleaned.get("password")
        if email and password:
            self.user = authenticate(self.request, username=email, password=password)
            if self.user is None:
                raise forms.ValidationError(_("Invalid email or password."))
        return cleaned

    def get_user(self) -> User | None:
        return self.user


class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(label=_("Full name"), max_length=150)
    phone = forms.CharField(label=_("Phone"), validators=[phone_validator])

    class Meta:
        model = User
        fields = ("full_name", "email", "phone")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.full_name = self.cleaned_data["full_name"]
        user.phone = self.cleaned_data["phone"]
        if commit:
            user.save()
        return user
